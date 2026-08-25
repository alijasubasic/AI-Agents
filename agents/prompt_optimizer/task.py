"""The task under improvement, and how it is scored.

Scoring is deterministic. Using a model to grade the output of a loop whose
purpose is to improve prompts would make the improvement signal itself
sampled — the number could move because the grader had a different day, and
nobody could tell that apart from a real gain.
"""

from __future__ import annotations

import re

from agents.prompt_optimizer.models import (
    CaseOutcome,
    Evaluation,
    Split,
    TaskCase,
)

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> str:
    """Fold an answer to its comparable form.

    Deliberately forgiving about formatting and strict about content: a model
    replying "Billing." instead of "billing" has answered correctly, and one
    replying "probably billing" has not answered the question that was asked.
    """
    return _NON_WORD.sub(" ", text.strip().lower()).strip()


def score_exact(produced: str, expected: str) -> float:
    """One for an exact match after normalisation, zero otherwise."""
    return 1.0 if normalise(produced) == normalise(expected) else 0.0


class PromptTask:
    """A set of cases, split into tuning and holdout, with a scorer."""

    def __init__(self, name: str, cases: list[TaskCase], baseline_prompt: str) -> None:
        if not cases:
            raise ValueError("a task needs cases")

        self.name = name
        self.cases = list(cases)
        self.baseline_prompt = baseline_prompt

        if not self.holdout:
            raise ValueError(
                "a task needs holdout cases; without them the loop measures on "
                "the examples it optimised against and every number is flattery"
            )

    def of(self, split: Split) -> list[TaskCase]:
        return [case for case in self.cases if case.split is split]

    @property
    def tuning(self) -> list[TaskCase]:
        return self.of(Split.TUNING)

    @property
    def holdout(self) -> list[TaskCase]:
        return self.of(Split.HOLDOUT)

    def evaluate(self, split: Split, answers: dict[str, str]) -> Evaluation:
        """Score one prompt version's answers over one split.

        A case with no answer scores zero rather than being skipped. Silently
        dropping it would let a prompt improve its average by failing to
        respond at all.
        """
        return Evaluation(
            split=split,
            outcomes=[
                CaseOutcome(
                    case_id=case.id,
                    produced=answers.get(case.id, ""),
                    expected=case.expected,
                    score=score_exact(answers.get(case.id, ""), case.expected),
                )
                for case in self.of(split)
            ],
        )

    def describe_failures(self, evaluation: Evaluation) -> str:
        """Render failures for the critic.

        Only ever called with a tuning evaluation. The holdout is not shown to
        the critic or the optimizer, and this function has no way to tell the
        difference — the caller is responsible, and a test checks it.
        """
        by_id = {case.id: case for case in self.cases}
        lines = []
        for outcome in evaluation.failures:
            case = by_id[outcome.case_id]
            lines.append(
                f"- input: {case.inputs}\n"
                f"  expected: {outcome.expected}\n"
                f"  produced: {outcome.produced or '(nothing)'}"
            )
        return "\n".join(lines) or "(no failures)"
