"""The evaluator-optimizer loop.

    evaluate → critique → propose → evaluate → accept or roll back

The loop is small. What matters is the gate at the end of it, and one rule
inside it:

**Acceptance is decided on the holdout split, which neither the critic nor the
optimizer has ever seen.** A prompt that improved on the cases it was shown and
did not improve on the ones it was not has learned those cases, and the loop
says so instead of counting it as progress.

The second rule is that a rejected version is not built on. Each iteration
proposes from the best *accepted* prompt, so a bad step is rolled back rather
than compounded — hill climbing, not a random walk.
"""

from __future__ import annotations

from collections.abc import Callable

from agents.self_improving.models import (
    Critique,
    Decision,
    ImprovementRun,
    Iteration,
    PromptProposal,
    PromptVersion,
    Split,
    TaskCase,
)
from agents.self_improving.task import PromptTask
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider

#: Executes one prompt version over a set of cases, returning case id to answer.
#: Abstracted so the demo can script it and a live run can call the model.
PromptRunner = Callable[[PromptVersion, list[TaskCase]], dict[str, str]]

CRITIC_PROMPT = """\
You review a prompt that is getting some cases wrong, and explain why.

You will be shown the prompt and the cases it failed. Look for the *pattern*
behind the failures, not the failures themselves. "Confuses questions about
money already spent with questions about a prospective purchase" is useful.
"Got the third one wrong" is not — the prompt cannot be fixed case by case,
and a prompt patched with individual examples memorises them.

You are shown a sample of failures, not all of them. Do not assume the ones you
cannot see look like the ones you can.
"""

OPTIMIZER_PROMPT = """\
You rewrite a system prompt to address a critique.

Rules:

- Write the whole replacement prompt, not a diff. A prompt assembled from
  fragments is one nobody can read afterwards.
- Address the pattern the critique names, in general terms. Do not enumerate
  the failing examples: a prompt that lists its test cases scores well on them
  and no better on anything else.
- Keep the output format exactly as it was. Changing it breaks every consumer
  of this prompt for a gain that has nothing to do with the task.
- Change as little as will do the job. A rewrite that changes everything makes
  it impossible to tell which part helped.
"""

CRITIC_TEMPLATE = """\
Prompt under review:

<<<PROMPT>>>
{prompt}
<<<END>>>

It scored {score:.0%} on the cases it was evaluated against. Failures:

{failures}
"""

OPTIMIZER_TEMPLATE = """\
Current prompt:

<<<PROMPT>>>
{prompt}
<<<END>>>

Critique:

Patterns: {patterns}
Suggestions: {suggestions}
Verdict: {verdict}
"""


class ImprovementLoop:
    """Improves one prompt against one task, and refuses to fool itself."""

    def __init__(
        self,
        *,
        task: PromptTask,
        runner: PromptRunner,
        critic_provider: LLMProvider,
        optimizer_provider: LLMProvider,
        settings: Settings | None = None,
        max_iterations: int = 3,
        min_gain: float = 0.0,
        max_cost_usd: float = 1.0,
    ) -> None:
        self.task = task
        self.runner = runner
        self.max_iterations = max_iterations
        self.min_gain = min_gain
        self.max_cost_usd = max_cost_usd
        self.settings = settings or Settings.from_env()

        self._critic = Agent(
            name="critic",
            system_prompt=CRITIC_PROMPT,
            provider=critic_provider,
            settings=self.settings,
        )
        self._optimizer = Agent(
            name="optimizer",
            system_prompt=OPTIMIZER_PROMPT,
            provider=optimizer_provider,
            settings=self.settings,
        )

    def run(self) -> ImprovementRun:
        """Improve the prompt, returning every version tried and what happened."""
        result = ImprovementRun(task=self.task.name)

        baseline = PromptVersion(number=0, text=self.task.baseline_prompt)
        best = self._evaluate(baseline)
        result.iterations.append(best)

        for number in range(1, self.max_iterations + 1):
            if result.total_cost_usd > self.max_cost_usd:
                result.halted_reason = (
                    f"cost budget exhausted: ${result.total_cost_usd:.4f} of "
                    f"${self.max_cost_usd:.4f}"
                )
                break

            critique, critique_cost = self._critique(best)
            proposal, proposal_cost = self._propose(best.version, critique)
            if proposal is None:
                result.halted_reason = "the optimizer produced no usable prompt"
                break

            candidate = PromptVersion(
                number=number,
                text=proposal.prompt,
                parent=best.version.number,
                rationale=proposal.rationale,
            )
            iteration = self._evaluate(candidate)
            iteration.critique = critique
            iteration.cost_usd = critique_cost + proposal_cost
            result.total_cost_usd += iteration.cost_usd

            self._decide(iteration, best)
            result.iterations.append(iteration)

            if iteration.accepted:
                best = iteration

        return result

    # -- internals -------------------------------------------------------

    def _evaluate(self, version: PromptVersion) -> Iteration:
        """Run a version over both splits and score it."""
        return Iteration(
            version=version,
            tuning=self.task.evaluate(Split.TUNING, self.runner(version, self.task.tuning)),
            holdout=self.task.evaluate(Split.HOLDOUT, self.runner(version, self.task.holdout)),
        )

    def _critique(self, iteration: Iteration) -> tuple[Critique, float]:
        """Ask the critic why the tuning cases failed.

        The tuning evaluation is passed deliberately and exclusively. A critic
        that has seen the holdout can leak it into its advice, and the split
        would then be decoration.
        """
        prompt = CRITIC_TEMPLATE.format(
            prompt=iteration.version.text,
            score=iteration.tuning.score,
            failures=self.task.describe_failures(iteration.tuning),
        )
        critique, run = self._critic.run_structured(prompt, Critique)
        return critique, run.cost_usd

    def _propose(
        self, version: PromptVersion, critique: Critique
    ) -> tuple[PromptProposal | None, float]:
        prompt = OPTIMIZER_TEMPLATE.format(
            prompt=version.text,
            patterns="; ".join(critique.patterns) or "none identified",
            suggestions="; ".join(critique.suggestions) or "none",
            verdict=critique.verdict or "n/a",
        )
        proposal, run = self._optimizer.run_structured(prompt, PromptProposal)
        if not proposal.prompt.strip():
            return None, run.cost_usd
        return proposal, run.cost_usd

    def _decide(self, candidate: Iteration, best: Iteration) -> None:
        """Accept or roll back, on the holdout score alone."""
        gain = candidate.holdout.score - best.holdout.score

        if gain < 0:
            candidate.decision = Decision.REJECTED_REGRESSION
            candidate.reason = (
                f"holdout fell from {best.holdout.score:.0%} to {candidate.holdout.score:.0%}"
            )
        elif gain <= self.min_gain:
            candidate.decision = Decision.REJECTED_NO_GAIN
            candidate.reason = f"holdout unchanged at {candidate.holdout.score:.0%}" + (
                f" while tuning rose to {candidate.tuning.score:.0%} — the "
                f"prompt learned the examples"
                if candidate.tuning.score > best.tuning.score
                else ""
            )
        else:
            candidate.decision = Decision.ACCEPTED
            candidate.reason = (
                f"holdout rose from {best.holdout.score:.0%} to {candidate.holdout.score:.0%}"
            )
