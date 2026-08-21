"""Writing one change for one finding.

The patcher asks a model for a replacement file and does nothing else with the
answer than write it down. Every judgement about whether the change is
acceptable happens afterwards, in `verifier.py`, where the patcher has no
influence over the outcome.

Whole files rather than diffs, deliberately. A unified diff that applies
cleanly to the wrong place is a class of bug that simply does not exist if the
agent has to write out what it means the file to contain, and a model that
cannot produce the whole file has not understood the change well enough to make
it.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from agents.improver.models import Finding, Patch
from agents.improver.safety import branch_name
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider

SYSTEM_PROMPT = """\
You make one small, isolated change to one file, addressing one finding.

Rules:

- Return the complete new contents of the file, not a diff and not a fragment.
- Change only what the finding is about. A patch that also tidies three other
  things is refused, not because the tidying is wrong but because nobody
  reviewed it.
- Keep the file's existing style: its naming, its comment density, its idiom.
  A change that reads as though a different person wrote it is harder to review
  than the problem it fixes.
- Never modify a test, an eval, or CI configuration. You cannot: those paths
  are refused before your output is written. If a test is wrong, say so in the
  rationale and change nothing.
- For a blocker or a major finding, also write a regression test that fails
  without your change. You cannot add it yourself — a person will — so write it
  to be pasted in as-is.
- If the finding is wrong, or you cannot fix it without changing more than this
  file, return the file unchanged and say why in the rationale. An honest
  refusal is a good outcome; a plausible change that does not fix the problem
  is not.
"""

PATCH_TEMPLATE = """\
Finding from the {reviewer} reviewer, severity {severity}:

  {title}
  {detail}

Suggested change:
  {suggestion}

Anchor (this snippet is in the file):
  {anchor}

<<<CURRENT CONTENTS OF {path}>>>
{source}
<<<END>>>
"""


class PatchDraft(BaseModel):
    """What the model returns."""

    new_contents: str = Field(
        description=(
            "The complete new contents of the file. Return it unchanged if you "
            "are not making the change."
        )
    )
    changed: bool = Field(
        description="False if you decided not to change anything, whatever the reason."
    )
    rationale: str = Field(description="What you changed and why, or why you did not.")
    regression_test: str = Field(
        default="",
        description=(
            "A pytest function that fails without this change, ready to paste "
            "into the file's test module. Empty for anything that is not a bug fix."
        ),
    )


class Patcher:
    """Turns one finding into one patch."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        settings: Settings | None = None,
        run_date: date | None = None,
    ) -> None:
        self.run_date = run_date or date.today()
        self._agent = Agent(
            name="patcher",
            system_prompt=SYSTEM_PROMPT,
            provider=provider,
            settings=settings,
        )

    def write(self, finding: Finding, source: str) -> tuple[Patch | None, float]:
        """Draft a patch for one finding.

        Returns `None` when the model declined to change anything, which is a
        legitimate outcome rather than a failure — a finding that turns out to
        be wrong should produce no patch, not a plausible one.
        """
        prompt = PATCH_TEMPLATE.format(
            reviewer=finding.reviewer.value,
            severity=finding.severity.label,
            title=finding.title,
            detail=finding.detail,
            suggestion=finding.suggestion,
            anchor=finding.anchor or "(none given)",
            path=finding.path,
            source=source,
        )
        draft, run = self._agent.run_structured(prompt, PatchDraft)

        if not draft.changed or draft.new_contents.strip() == source.strip():
            return None, run.cost_usd

        patch = Patch(
            finding=finding,
            branch=branch_name(self.run_date, finding.title),
            allowed_paths=[finding.path],
            changes={finding.path: draft.new_contents},
            regression_test=draft.regression_test,
            rationale=draft.rationale,
        )
        return patch, run.cost_usd
