"""Data models for the evaluator-optimizer loop.

A self-improving agent is easy to build and easy to build wrong. The wrong
version rewrites its prompt, measures the result on the same examples it was
shown, sees the number go up, and reports success. What it has learned is those
examples.

Two things in these models exist to prevent that:

* `TaskCase.split` divides the cases into a **tuning** set the optimizer may
  see and a **holdout** set it never does. Acceptance is decided on the
  holdout.
* `Iteration` records both scores separately, so a version that improved on
  tuning and fell on holdout is visible as exactly that rather than averaged
  into a single flattering number.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Split(StrEnum):
    """Which half of the cases a case belongs to."""

    #: Shown to the critic and the optimizer. They may learn these.
    TUNING = "tuning"

    #: Never shown to either. The only thing acceptance is decided on.
    HOLDOUT = "holdout"


class TaskCase(BaseModel):
    """One scored example of the task being improved."""

    id: str
    split: Split
    inputs: str = Field(description="What the prompt is given.")
    expected: str = Field(description="The correct output.")
    note: str = ""


class CaseOutcome(BaseModel):
    """What one prompt version produced for one case."""

    case_id: str
    produced: str
    expected: str
    score: float = Field(ge=0.0, le=1.0)

    @property
    def passed(self) -> bool:
        return self.score >= 1.0


class Evaluation(BaseModel):
    """One prompt version, run over one split."""

    split: Split
    outcomes: list[CaseOutcome] = Field(default_factory=list)

    @property
    def score(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(outcome.score for outcome in self.outcomes) / len(self.outcomes)

    @property
    def failures(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.passed]


class PromptVersion(BaseModel):
    """One version of the system prompt under improvement."""

    number: int
    text: str
    parent: int | None = None
    rationale: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def label(self) -> str:
        return f"v{self.number}"


class Critique(BaseModel):
    """The critic's reading of what went wrong.

    Field descriptions are prompt text. The critic is shown failures from the
    **tuning** split only, and is told so — a critic that has seen the holdout
    can leak it into its advice, which would defeat the split entirely.
    """

    patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Failure patterns you can see across the examples, not a list of "
            "individual mistakes. 'Confuses billing questions with sales' is "
            "useful; 'got case 3 wrong' is not."
        ),
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Concrete changes to the instructions that would address those patterns.",
    )
    verdict: str = Field(
        default="", description="One sentence on whether this prompt is close or far off."
    )


class PromptProposal(BaseModel):
    """The optimizer's replacement prompt."""

    prompt: str = Field(
        description=(
            "The full replacement system prompt. Write the whole thing, not a "
            "diff — a prompt assembled from fragments is one nobody can read."
        )
    )
    rationale: str = Field(description="One or two sentences on what changed and why.")


class Decision(StrEnum):
    """What the loop did with a proposed version."""

    ACCEPTED = "accepted"
    REJECTED_REGRESSION = "rejected_regression"
    REJECTED_NO_GAIN = "rejected_no_gain"


class Iteration(BaseModel):
    """One turn of the loop."""

    version: PromptVersion
    tuning: Evaluation
    holdout: Evaluation
    critique: Critique | None = None
    decision: Decision | None = None
    reason: str = ""
    cost_usd: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.decision is Decision.ACCEPTED

    @property
    def overfit_gap(self) -> float:
        """Tuning score minus holdout score.

        A large positive gap is the signature of a prompt that learned the
        examples rather than the task.
        """
        return self.tuning.score - self.holdout.score


class ImprovementRun(BaseModel):
    """A whole improvement session."""

    task: str
    iterations: list[Iteration] = Field(default_factory=list)
    halted_reason: str | None = None
    total_cost_usd: float = 0.0

    @property
    def baseline(self) -> Iteration | None:
        return self.iterations[0] if self.iterations else None

    @property
    def best(self) -> Iteration | None:
        """The accepted version with the highest holdout score.

        The baseline counts: if nothing beat it, it is still the answer.
        """
        candidates = [it for it in self.iterations if it.accepted or it is self.baseline]
        return max(candidates, key=lambda it: it.holdout.score) if candidates else None

    @property
    def improvement(self) -> float:
        """Holdout gain from baseline to best. Zero when nothing was accepted."""
        if not self.baseline or not self.best:
            return 0.0
        return self.best.holdout.score - self.baseline.holdout.score

    @property
    def accepted_count(self) -> int:
        return sum(1 for iteration in self.iterations if iteration.accepted)
