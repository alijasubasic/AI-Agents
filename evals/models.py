"""Data models for the eval suite.

Every agent README in this repository says the same thing: the scripted mocks
prove the plumbing, not the prompt. This package is where that gap gets
measured instead of merely admitted.

The central distinction is `Layer`. Some behaviour is deterministic code and
can be scored in CI on every commit; some is the model's judgement and can only
be scored against the real API. Mixing the two produces a number that looks
like quality and measures neither, so each case declares which it is.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Layer(StrEnum):
    """What a case actually tests."""

    #: Deterministic code — policies, engines, verification. Runs in CI, free,
    #: identical every time.
    LOGIC = "logic"

    #: The model's judgement. Needs a live API key; scores are sampled, not
    #: exact. Never runs in CI.
    JUDGEMENT = "judgement"


class Expectation(StrEnum):
    """Whether the case is expected to pass.

    `KNOWN_GAP` is the reason this enum exists. Some cases document a real
    limitation — a paraphrase the grounding check cannot catch, an injection
    phrased in German. They are kept, they fail, and they fail *visibly*.
    Deleting them would make the score look better and the agent no safer.
    """

    PASS = "pass"
    KNOWN_GAP = "known_gap"


class EvalCase(BaseModel):
    """One scored test of an agent's behaviour."""

    id: str
    agent: str
    layer: Layer
    description: str = Field(description="What behaviour this case checks, in one line.")
    expectation: Expectation = Expectation.PASS

    #: Why this case exists, especially when it is a known gap.
    note: str = ""

    #: Free-form payload the runner hands to the case's own function.
    inputs: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_known_gap(self) -> bool:
        return self.expectation is Expectation.KNOWN_GAP


class Score(BaseModel):
    """The outcome of one case.

    A score is a float in [0, 1] rather than a boolean so partial credit is
    possible: an extraction that gets four of five fields right is not the same
    as one that gets none, and a suite that cannot tell them apart cannot show
    an improvement.
    """

    value: float = Field(ge=0.0, le=1.0)
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.value >= 1.0

    @classmethod
    def hit(cls, detail: str = "") -> Score:
        return cls(value=1.0, detail=detail)

    @classmethod
    def miss(cls, detail: str) -> Score:
        return cls(value=0.0, detail=detail)

    @classmethod
    def partial(cls, value: float, detail: str) -> Score:
        return cls(value=value, detail=detail)


class CaseResult(BaseModel):
    """One case, run."""

    case: EvalCase
    score: Score
    error: str | None = None

    @property
    def value(self) -> float:
        return 0.0 if self.error else self.score.value

    @property
    def as_expected(self) -> bool:
        """Whether the outcome matched what the case said would happen.

        A known gap that fails is behaving as documented. A known gap that
        *passes* is news — it means someone fixed it and forgot to update the
        case, which is worth surfacing rather than silently counting as a win.
        """
        if self.case.is_known_gap:
            return self.value < 1.0
        return self.value >= 1.0 and self.error is None


class SuiteResult(BaseModel):
    """Every case for one agent."""

    agent: str
    results: list[CaseResult] = Field(default_factory=list)

    @property
    def scored(self) -> list[CaseResult]:
        """Cases that count towards the headline score.

        Known gaps are excluded: they are documentation, and letting them drag
        the number down would create pressure to delete them.
        """
        return [result for result in self.results if not result.case.is_known_gap]

    @property
    def gaps(self) -> list[CaseResult]:
        return [result for result in self.results if result.case.is_known_gap]

    @property
    def score(self) -> float:
        """Mean score over the cases that count. 1.0 when there are none."""
        if not self.scored:
            return 1.0
        return sum(result.value for result in self.scored) / len(self.scored)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.scored if result.value >= 1.0)

    @property
    def surprises(self) -> list[CaseResult]:
        """Anything that did not behave as its case said it would."""
        return [result for result in self.results if not result.as_expected]

    @property
    def is_clean(self) -> bool:
        return not self.surprises


class EvalReport(BaseModel):
    """Every suite, run together."""

    layer: Layer
    suites: list[SuiteResult] = Field(default_factory=list)

    @property
    def score(self) -> float:
        """Mean across suites, weighting each agent equally.

        Not a mean across cases: an agent with forty cases would otherwise
        drown out one with ten, and the number would track how much test-writing
        an agent attracted rather than how well it works.
        """
        if not self.suites:
            return 1.0
        return sum(suite.score for suite in self.suites) / len(self.suites)

    @property
    def total_cases(self) -> int:
        return sum(len(suite.results) for suite in self.suites)

    @property
    def surprises(self) -> list[CaseResult]:
        return [result for suite in self.suites for result in suite.surprises]

    @property
    def is_clean(self) -> bool:
        return not self.surprises
