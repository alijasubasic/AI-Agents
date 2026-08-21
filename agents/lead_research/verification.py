"""Deterministic verification of researched facts.

The model proposes claims with citations. This module decides what each one is
actually worth, and it does so without asking a model anything — it either finds
the quote in the cited document or it does not.

Five outcomes, in the order they are checked:

    UNSOURCED      no source cited at all
    MISATTRIBUTED  source cited, but it does not contain the quote
    DISPUTED       another source gives a different value for the same field
    STALE          verified, but the document is old enough to have moved on
    VERIFIED       none of the above

`UNSOURCED` is not treated as a failure of the model. Some things genuinely are
not on the public web, and a model that says so is behaving correctly. What
would be a failure is presenting such a claim as though it were sourced, and
that is exactly what this labelling prevents.
"""

from __future__ import annotations

import re
from datetime import date

from agents.lead_research.models import (
    Fact,
    FactStatus,
    Source,
    VerifiedFact,
)

#: A source older than this is verified but flagged: headcounts and funding
#: rounds move, and a two-year-old figure quoted as current is how a sales call
#: starts badly.
STALENESS_MONTHS = 18

#: Fields where two different values genuinely conflict. Free-text fields like
#: `sector` can differ between sources without either being wrong.
CONTESTABLE_FIELDS = frozenset({"headquarters", "headcount", "founded", "ceo", "funding"})


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace, so line wrapping does not defeat a match."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def quote_supports(quote: str, source: Source) -> bool:
    """True if `quote` appears in the source text.

    Substring matching after whitespace normalisation. Deliberately strict: the
    schema asks the model to copy a sentence verbatim, so a paraphrase failing
    this check is the check working. A model that cannot find a supporting
    sentence should be reporting no source, not an approximate one.
    """
    if not quote.strip():
        return False
    return _normalise(quote) in _normalise(source.text)


def find_disputes(facts: list[Fact]) -> dict[str, set[str]]:
    """Map each contested field to the distinct values claimed for it.

    Only fields in `CONTESTABLE_FIELDS` count. Two sources describing a sector
    differently are both fine; two sources placing the head office in different
    cities are not.
    """
    values: dict[str, set[str]] = {}
    for fact in facts:
        if fact.field in CONTESTABLE_FIELDS:
            values.setdefault(fact.field, set()).add(_normalise(fact.value))
    return {field: seen for field, seen in values.items() if len(seen) > 1}


def verify_fact(
    fact: Fact,
    sources: dict[str, Source],
    *,
    today: date,
    disputed_fields: set[str] | None = None,
) -> VerifiedFact:
    """Label one claim."""
    disputed_fields = disputed_fields or set()

    if not fact.source_id:
        return VerifiedFact(
            fact=fact,
            status=FactStatus.UNSOURCED,
            note="no source cited; state this as unconfirmed or leave it out",
        )

    source = sources.get(fact.source_id)
    if source is None:
        return VerifiedFact(
            fact=fact,
            status=FactStatus.MISATTRIBUTED,
            note=f"cited source {fact.source_id!r} was never retrieved",
        )

    if not quote_supports(fact.quote, source):
        return VerifiedFact(
            fact=fact,
            status=FactStatus.MISATTRIBUTED,
            source=source,
            note="the quoted sentence does not appear in the cited source",
        )

    if fact.field in disputed_fields:
        return VerifiedFact(
            fact=fact,
            status=FactStatus.DISPUTED,
            source=source,
            note="another retrieved source gives a different value for this field",
        )

    if source.published is not None:
        age = _months_between(source.published, today)
        if age > STALENESS_MONTHS:
            return VerifiedFact(
                fact=fact,
                status=FactStatus.STALE,
                source=source,
                note=f"source is {age} months old; the value may have moved since",
            )

    return VerifiedFact(fact=fact, status=FactStatus.VERIFIED, source=source)


def verify_all(facts: list[Fact], sources: list[Source], *, today: date) -> list[VerifiedFact]:
    """Label every claim, taking cross-source disputes into account."""
    by_id = {source.id: source for source in sources}
    disputed = set(find_disputes(facts))
    return [verify_fact(fact, by_id, today=today, disputed_fields=disputed) for fact in facts]
