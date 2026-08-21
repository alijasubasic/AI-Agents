"""Scorers.

Small, deterministic functions turning "what the agent did" into a number. They
exist so cases read as declarations rather than as piles of assertions, and so
partial credit is expressed once rather than reinvented per case.

Nothing here calls a model. Scoring with a model is a legitimate technique and
a bad fit for this suite: it would make the eval numbers themselves sampled,
which is exactly the property the LOGIC layer is supposed to be free of.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from evals.models import Score


def equals(actual: Any, expected: Any, *, label: str = "value") -> Score:
    """Full marks for an exact match."""
    if actual == expected:
        return Score.hit(f"{label} == {expected!r}")
    return Score.miss(f"{label} was {actual!r}, expected {expected!r}")


def is_true(actual: bool, *, label: str) -> Score:
    return Score.hit(label) if actual else Score.miss(f"expected {label}")


def is_false(actual: bool, *, label: str) -> Score:
    return Score.hit(f"not {label}") if not actual else Score.miss(f"expected not {label}")


def contains_all(haystack: str, needles: Iterable[str], *, label: str = "text") -> Score:
    """Partial credit for each phrase present.

    Used where an agent must mention several things and the order does not
    matter — an escalation naming four reasons, a report listing three sources.
    """
    wanted = list(needles)
    if not wanted:
        return Score.hit(f"{label}: nothing required")

    lowered = haystack.lower()
    found = [needle for needle in wanted if needle.lower() in lowered]
    if len(found) == len(wanted):
        return Score.hit(f"{label} contains all {len(wanted)}")

    missing = [needle for needle in wanted if needle not in found]
    return Score.partial(
        len(found) / len(wanted),
        f"{label} missing {len(missing)} of {len(wanted)}: {', '.join(missing[:3])}",
    )


def excludes_all(haystack: str, forbidden: Iterable[str], *, label: str = "text") -> Score:
    """Full marks only when none of the phrases appear.

    Deliberately all-or-nothing. "Mostly did not leak the customer's phone
    number" is not a partial success.
    """
    lowered = haystack.lower()
    leaked = [needle for needle in forbidden if needle.lower() in lowered]
    if not leaked:
        return Score.hit(f"{label} contains none of the forbidden phrases")
    return Score.miss(f"{label} leaked: {', '.join(leaked[:3])}")


def set_equals(actual: Iterable[Any], expected: Iterable[Any], *, label: str = "set") -> Score:
    """Partial credit by Jaccard overlap, so near-misses are visible."""
    got, want = set(actual), set(expected)
    if got == want:
        return Score.hit(f"{label} matches exactly")

    union = got | want
    overlap = len(got & want) / len(union) if union else 1.0
    missing = sorted(str(item) for item in want - got)
    extra = sorted(str(item) for item in got - want)

    parts = []
    if missing:
        parts.append(f"missing {missing}")
    if extra:
        parts.append(f"unexpected {extra}")
    return Score.partial(overlap, f"{label}: {'; '.join(parts)}")


def within(actual: float, expected: float, *, tolerance: float, label: str = "value") -> Score:
    """Full marks inside the tolerance, nothing outside it."""
    if abs(actual - expected) <= tolerance:
        return Score.hit(f"{label} {actual} within {tolerance} of {expected}")
    return Score.miss(f"{label} was {actual}, expected {expected} ± {tolerance}")


def at_least(actual: float, floor: float, *, label: str = "value") -> Score:
    if actual >= floor:
        return Score.hit(f"{label} {actual} >= {floor}")
    return Score.miss(f"{label} was {actual}, expected at least {floor}")


def at_most(actual: float, ceiling: float, *, label: str = "value") -> Score:
    if actual <= ceiling:
        return Score.hit(f"{label} {actual} <= {ceiling}")
    return Score.miss(f"{label} was {actual}, expected at most {ceiling}")


def combine(*scores: Score) -> Score:
    """Average several scores into one, keeping every detail.

    Used where a case checks a handful of related things and each should carry
    equal weight — the classification is right *and* the routing is right *and*
    nothing leaked.
    """
    if not scores:
        return Score.hit("nothing to combine")

    value = sum(score.value for score in scores) / len(scores)
    failures = [score.detail for score in scores if score.value < 1.0]
    detail = "; ".join(failures) if failures else "; ".join(s.detail for s in scores)
    return Score(value=value, detail=detail)
