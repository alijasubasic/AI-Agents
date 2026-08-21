"""Tests for the fact verification layer.

No model touches any of this. These tests are what makes the claim "every fact
was checked against the document it cited" true rather than decorative.
"""

from __future__ import annotations

from datetime import date

from agents.lead_research.models import Fact, FactStatus, Source, SourceKind
from agents.lead_research.verification import (
    STALENESS_MONTHS,
    find_disputes,
    quote_supports,
    verify_all,
    verify_fact,
)

TODAY = date(2026, 3, 5)


def source(
    source_id: str = "s1",
    text: str = "Acme Ltd is headquartered in Leeds and was founded in 2011.",
    published: date | None = date(2026, 1, 1),
) -> Source:
    return Source(
        id=source_id,
        url=f"https://example.test/{source_id}",
        title=f"Doc {source_id}",
        kind=SourceKind.COMPANY_SITE,
        published=published,
        text=text,
    )


def fact(**overrides) -> Fact:
    base = {
        "field": "headquarters",
        "value": "Leeds",
        "source_id": "s1",
        "quote": "Acme Ltd is headquartered in Leeds and was founded in 2011.",
    }
    return Fact(**{**base, **overrides})


def verify(f: Fact, *sources: Source, today: date = TODAY):
    return verify_fact(f, {s.id: s for s in sources}, today=today)


# --- quote matching -----------------------------------------------------


def test_a_verbatim_quote_is_found():
    assert quote_supports("headquartered in Leeds", source()) is True


def test_matching_ignores_case_and_line_wrapping():
    doc = source(text="Acme Ltd is\n  headquartered   in Leeds.")
    assert quote_supports("HEADQUARTERED IN LEEDS", doc) is True


def test_a_paraphrase_is_not_a_match():
    # The schema asks for a verbatim sentence. A model that can only paraphrase
    # should be reporting no source, not an approximate one.
    assert quote_supports("Acme is based in Leeds", source()) is False


def test_an_empty_quote_never_matches():
    assert quote_supports("", source()) is False
    assert quote_supports("   ", source()) is False


# --- statuses -----------------------------------------------------------


def test_a_supported_recent_claim_is_verified():
    result = verify(fact(), source())
    assert result.status is FactStatus.VERIFIED
    assert result.is_usable is True
    assert result.source is not None


def test_a_claim_with_no_source_is_unsourced():
    result = verify(fact(source_id=None, quote=""), source())
    assert result.status is FactStatus.UNSOURCED
    assert result.is_usable is False


def test_a_claim_citing_a_document_that_was_never_retrieved_is_misattributed():
    result = verify(fact(source_id="s-does-not-exist"), source())
    assert result.status is FactStatus.MISATTRIBUTED
    assert "never retrieved" in result.note


def test_a_claim_whose_quote_is_absent_is_misattributed():
    result = verify(fact(quote="Acme Ltd employs 400 people."), source())
    assert result.status is FactStatus.MISATTRIBUTED
    # The source is still attached, so a reader can go and look.
    assert result.source is not None


def test_a_claim_from_an_old_document_is_stale():
    old = source(published=date(2021, 1, 1))
    result = verify(fact(), old)

    assert result.status is FactStatus.STALE
    assert "months old" in result.note


def test_a_document_just_inside_the_staleness_window_is_still_verified():
    edge = source(published=date(2026, 3, 5).replace(year=2024, month=9))
    months = (2026 - 2024) * 12 + (3 - 9)
    assert months == STALENESS_MONTHS

    assert verify(fact(), edge).status is FactStatus.VERIFIED


def test_a_document_with_no_publication_date_is_not_treated_as_stale():
    # Absence of a date is not evidence of age. Real pages often have none.
    undated = source(published=None)
    assert verify(fact(), undated).status is FactStatus.VERIFIED


# --- disputes -----------------------------------------------------------


def test_two_values_for_a_contested_field_are_a_dispute():
    facts = [fact(value="Leeds"), fact(value="Bristol", source_id="s2")]
    assert set(find_disputes(facts)) == {"headquarters"}


def test_the_same_value_twice_is_not_a_dispute():
    facts = [fact(value="Leeds"), fact(value="leeds", source_id="s2")]
    assert find_disputes(facts) == {}


def test_free_text_fields_are_not_contested():
    # Two sources describing a sector differently are both fine.
    facts = [
        fact(field="sector", value="Industrial equipment"),
        fact(field="sector", value="Warehouse hardware", source_id="s2"),
    ]
    assert find_disputes(facts) == {}


def test_both_sides_of_a_dispute_are_flagged():
    doc_a = source("s1", text="Acme Ltd is headquartered in Leeds.")
    doc_b = source("s2", text="Acme Ltd is headquartered in Bristol.")
    facts = [
        fact(value="Leeds", quote="Acme Ltd is headquartered in Leeds."),
        fact(value="Bristol", source_id="s2", quote="Acme Ltd is headquartered in Bristol."),
    ]

    results = verify_all(facts, [doc_a, doc_b], today=TODAY)

    # Neither wins. The reader is told there was a disagreement at all, which is
    # the fact that actually matters to them.
    assert [r.status for r in results] == [FactStatus.DISPUTED, FactStatus.DISPUTED]


def test_an_unsupported_quote_is_misattributed_even_when_the_field_is_disputed():
    # Checked in order: a claim that fails on its own evidence is reported as
    # such rather than being softened into a disagreement.
    doc_a = source("s1", text="Acme Ltd is headquartered in Leeds.")
    doc_b = source("s2", text="Acme Ltd is headquartered in Bristol.")
    facts = [
        fact(value="Leeds", quote="Acme Ltd is headquartered in Leeds."),
        fact(value="Bristol", source_id="s2", quote="A sentence nobody wrote."),
    ]

    results = verify_all(facts, [doc_a, doc_b], today=TODAY)
    assert results[1].status is FactStatus.MISATTRIBUTED


# --- batch --------------------------------------------------------------


def test_verifying_nothing_returns_nothing():
    assert verify_all([], [source()], today=TODAY) == []


def test_every_fact_gets_exactly_one_label():
    facts = [fact(), fact(source_id=None, quote=""), fact(quote="not present")]
    results = verify_all(facts, [source()], today=TODAY)

    assert len(results) == 3
    assert [r.status for r in results] == [
        FactStatus.VERIFIED,
        FactStatus.UNSOURCED,
        FactStatus.MISATTRIBUTED,
    ]


def test_render_marks_anything_unverified():
    verified = verify(fact(), source())
    unsourced = verify(fact(source_id=None, quote=""), source())

    assert "[" not in verified.render().split("—")[0].split(":")[1]
    assert "UNSOURCED" in unsourced.render()
