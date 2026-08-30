"""Declaring and collecting eval cases.

A case is a function returning a `Score`, decorated with what it is testing:

    @case(
        id="triage-hostile-escalates",
        agent="email-triage",
        layer=Layer.LOGIC,
        description="A hostile complaint always reaches a human.",
    )
    def _() -> Score:
        ...

The decorator keeps the metadata next to the assertion instead of in a table
somewhere else, which is the difference between a case list that stays accurate
and one that rots.
"""

from __future__ import annotations

from collections.abc import Callable

from evals.models import EvalCase, Expectation, Layer, Score

CaseFn = Callable[[], Score]

#: Every registered case, in declaration order.
REGISTRY: list[tuple[EvalCase, CaseFn]] = []


def case(
    *,
    id: str,  # noqa: A002 - "id" reads correctly here and shadows nothing used
    agent: str,
    layer: Layer,
    description: str,
    expectation: Expectation = Expectation.PASS,
    note: str = "",
) -> Callable[[CaseFn], CaseFn]:
    """Register one eval case."""

    def register(fn: CaseFn) -> CaseFn:
        if any(existing.id == id for existing, _ in REGISTRY):
            raise ValueError(f"Duplicate eval case id: {id!r}")

        REGISTRY.append(
            (
                EvalCase(
                    id=id,
                    agent=agent,
                    layer=layer,
                    description=description,
                    expectation=expectation,
                    note=note,
                ),
                fn,
            )
        )
        return fn

    return register


def load_all() -> list[tuple[EvalCase, CaseFn]]:
    """Import every case module and return the registry.

    Importing for side effects is not elegant, and the alternative — a manual
    list of every case — is a file people forget to update. This one cannot
    drift: a case that is not imported does not exist.
    """
    from evals.cases import (  # noqa: F401
        calendar_booking,
        call_intake,
        code_reviewer,
        email_triage,
        knowledge_base,
        lead_research,
        outreach,
        prompt_optimizer,
        prospecting,
        supervisor,
    )

    return list(REGISTRY)


def clear() -> None:
    """Empty the registry. For tests that register throwaway cases."""
    REGISTRY.clear()
