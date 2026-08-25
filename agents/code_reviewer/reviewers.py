"""The reviewer crew.

Five reviewers read the same file for five different things. Running them
separately rather than asking one reviewer for everything is the whole point:
a single "review this file" prompt produces a list dominated by whatever the
model noticed first, and the categories nobody asked about go unmentioned.

Each reviewer gets its own narrow brief, and the briefs are written to push
against the usual failure of automated review — a long list of confident,
trivial observations. Every one of them is told that most findings are minor
and to say so.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agents.code_reviewer.models import Finding, Reviewer
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider

SHARED_RULES = """\
Rules that apply whatever you are looking for:

- Report what is actually wrong, not what is merely unusual. A style you would
  not have chosen is not a finding.
- Severity honestly. Most real findings are minor or nit. Marking everything
  major to seem thorough makes the whole list useless, because the reader stops
  believing any of it.
- Quote a short verbatim snippet as the anchor. It is checked against the file,
  so copy it rather than describing where you mean.
- If the file is fine in your area, say so with an empty list. A reviewer that
  never finds nothing is a reviewer nobody can trust when it finds something.
- Never suggest changing a test, an eval, or CI configuration. If one of those
  is wrong, that is a finding about the test — a person will act on it.
"""

BRIEFS: dict[Reviewer, str] = {
    Reviewer.CORRECTNESS: """\
You review code for logic errors.

Look for: conditions that are inverted or off by one, edge cases the code does
not handle (empty input, a single element, equal values, zero, a boundary hit
exactly), assumptions the surrounding code does not guarantee, and results that
are silently wrong rather than raising.

You are not looking for style, naming, or missing tests.
""",
    Reviewer.SECURITY: """\
You review code for security problems.

Look for: credentials or tokens in source, input from outside the system used
without validation, text from a tool result or a document treated as
instructions rather than data, paths built from untrusted input, and anything
that would let a caller reach further than intended.

Prompt injection through tool output is a real category here, not a
hypothetical one: anything an agent retrieves is written by somebody else.
""",
    Reviewer.ROBUSTNESS: """\
You review code for how it behaves when things go wrong.

Look for: failures that are swallowed, external calls with no timeout, retries
without a ceiling, rate limits nobody handles, resources that are not released,
and error paths that lose the information a person would need to diagnose the
problem.

A function that cannot fail is not your concern. One that can fail and does not
say so is.
""",
    Reviewer.READABILITY: """\
You review code for whether the next person can follow it.

Look for: names that mislead, dead code and unreachable branches, missing type
annotations on a public boundary, missing docstrings where the *why* is not
obvious from the code, and comments that describe what the line does rather
than why it does it.

Do not suggest reformatting. A formatter already runs on this repository.
""",
    Reviewer.AGENT_QUALITY: """\
You review the parts of the code that make an agent behave well.

Look for: system prompts that state a goal without stating what to do when it
cannot be met, tool descriptions too vague for a model to choose correctly,
output schemas whose field descriptions are documentation for a reader rather
than instructions for a model, loops with no stopping condition, and decisions
left to a model that deterministic code could make identically every time.

That last one is the most valuable finding you can make in this codebase.
""",
}

FILE_TEMPLATE = """\
File: {path}
{lines} lines, {function_count} top-level definitions, {tests}

<<<SOURCE>>>
{source}
<<<END SOURCE>>>
"""


class ReviewResult(BaseModel):
    """What one reviewer returns.

    A list rather than a single finding, and explicitly allowed to be empty —
    the schema itself has to permit "nothing here", or the model will invent
    something to fill it.
    """

    findings: list[Finding] = Field(
        default_factory=list,
        description="Everything you found in your area. Empty is a valid answer.",
    )


def review_prompt(reviewer: Reviewer) -> str:
    return f"{BRIEFS[reviewer]}\n{SHARED_RULES}"


class ReviewerCrew:
    """Runs every reviewer over one file.

    Sequential rather than parallel. The loop in `core/` is synchronous, and
    making it concurrent to save a few seconds on a weekly job would be
    optimising the wrong thing.
    """

    def __init__(
        self,
        *,
        providers: dict[Reviewer, LLMProvider],
        settings: Settings | None = None,
    ) -> None:
        missing = set(Reviewer) - set(providers)
        if missing:
            raise ValueError(
                f"no provider for {', '.join(sorted(r.value for r in missing))}; "
                f"a crew missing a reviewer silently stops checking that category"
            )

        self.settings = settings or Settings.from_env()
        self._agents = {
            reviewer: Agent(
                name=f"reviewer-{reviewer.value}",
                system_prompt=review_prompt(reviewer),
                provider=provider,
                settings=self.settings,
            )
            for reviewer, provider in providers.items()
        }

    def review(self, path: str, source: str, *, has_tests: bool) -> tuple[list[Finding], float]:
        """Run the whole crew over one file. Returns findings and what it cost."""
        prompt = FILE_TEMPLATE.format(
            path=path,
            lines=len(source.splitlines()),
            function_count=source.count("\ndef ") + source.count("\nclass "),
            tests="has tests" if has_tests else "NO TESTS",
            source=source,
        )

        findings: list[Finding] = []
        cost = 0.0

        for reviewer, agent in self._agents.items():
            result, run = agent.run_structured(prompt, ReviewResult)
            cost += run.cost_usd
            # The reviewer is told which role it holds, but the record is set
            # here rather than trusted from the response: a model that
            # mislabels its own findings would scramble the crew's output.
            for finding in result.findings:
                findings.append(finding.model_copy(update={"reviewer": reviewer, "path": path}))

        return findings, cost


def anchor_is_real(finding: Finding, source: str) -> bool:
    """Whether the finding's quoted snippet actually appears in the file.

    Same idea as the citation checks elsewhere in this repository: a finding
    whose anchor is invented is a finding about a file the reviewer did not
    read carefully, and acting on it means patching something that is not there.
    """
    if not finding.anchor.strip():
        return False
    return " ".join(finding.anchor.split()) in " ".join(source.split())
