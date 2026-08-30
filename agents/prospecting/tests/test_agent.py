"""Tests for the prospecting agent end to end, on the fixture platforms."""

from __future__ import annotations

import pytest

from agents.prospecting.agent import ProspectingAgent, default_plan, lead_row, render_table
from agents.prospecting.fixtures import AREA
from agents.prospecting.models import ContactStatus, Lead, Platform, ProspectingResult
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for
from core.config import Settings


def settings() -> Settings:
    return Settings(trace_enabled=False)


def build(*, with_pages: bool = True, with_model: bool = True) -> ProspectingAgent:
    return ProspectingAgent(
        places=[
            MockPlaces(Platform.GOOGLE_MAPS),
            MockPlaces(Platform.OPENSTREETMAP),
            MockPlaces(Platform.DIRECTORY),
        ],
        pages=MockPages() if with_pages else None,
        provider=provider_for(AREA.what) if with_model else None,
        settings=settings(),
    )


def result() -> ProspectingResult:
    return build().find(AREA)


def by_name(found: ProspectingResult, name: str) -> Lead:
    return next(lead for lead in found.leads if lead.name == name)


# --- The search ---------------------------------------------------------


def test_every_platform_is_searched():
    agent = build()
    agent.find(AREA)

    assert all(place.queries for place in agent.places)


def test_the_agent_runs_without_a_model_at_all():
    """The plan is the only model call, and a deterministic one exists."""
    found = build(with_model=False).find(AREA)

    assert found.plan == default_plan(AREA)
    assert found.cost_usd == 0.0
    assert found.leads


def test_a_comparison_portal_is_excluded_by_the_plan():
    names = [lead.name for lead in result().leads]

    assert not any("Vergleich24" in name for name in names)


def test_duplicates_across_platforms_are_merged():
    found = result()

    assert found.duplicates_merged > 0
    assert len(found.leads) < found.listings_seen


# --- What each lead ends up with ----------------------------------------


def test_a_business_on_three_platforms_keeps_all_three():
    lead = by_name(result(), "Alpenblick Dach & Fassade")

    assert set(lead.platforms) >= {Platform.GOOGLE_MAPS, Platform.OPENSTREETMAP, Platform.DIRECTORY}


def test_the_imprint_supplies_the_address_no_map_platform_has():
    lead = by_name(result(), "Reiter Bedachungen GmbH")
    best = lead.best_email()

    assert best is not None
    assert best.value == "m.reiter@reiter-bedachungen.example"
    assert best.status is ContactStatus.CONFIRMED
    assert best.source_url.startswith("https://reiter-bedachungen.example")


def test_without_reading_websites_there_are_almost_no_addresses():
    """The uncomfortable fact about map data: it has phone numbers, not emails."""
    found = build(with_pages=False).find(AREA)

    assert found.contactable == []


def test_a_named_person_with_no_address_gets_a_labelled_guess():
    lead = by_name(result(), "Dachdeckerei Sailer & Sohn")
    guesses = [c for c in lead.emails if c.status is ContactStatus.CONSTRUCTED]

    assert [c.value for c in guesses] == ["s.sailer@sailer-dach.example"]
    assert lead.best_email() is None
    assert not lead.is_contactable


def test_a_directory_address_never_becomes_confirmed():
    lead = by_name(result(), "Alpenblick Dach & Fassade")

    assert [c.status for c in lead.emails] == [ContactStatus.REPORTED]
    assert not lead.is_contactable


def test_the_office_line_is_preferred_over_the_owners_mobile():
    lead = by_name(result(), "Reiter Bedachungen GmbH")
    phone = lead.best_phone()

    assert phone is not None
    assert phone.value == "+498955501234"


def test_contactable_leads_come_first():
    found = result()
    contactable = [lead.is_contactable for lead in found.leads]

    assert contactable == sorted(contactable, reverse=True)


def test_every_contact_detail_carries_a_source():
    for lead in result().leads:
        for contact in lead.contacts:
            assert contact.source_url, f"{lead.name}: {contact.value} has no source"


# --- What comes out -----------------------------------------------------


def test_the_export_row_says_what_each_detail_is_worth():
    row = lead_row(by_name(result(), "Dachdeckerei Sailer & Sohn"))

    assert "geraten" in row
    assert "s.sailer@sailer-dach.example" in row


def test_missing_fields_are_named_rather_than_left_blank():
    lead = by_name(result(), "Bauzentrum Isartal e.K.")

    assert lead.missing == ["Ansprechpartner"]


def test_the_table_renders_every_lead():
    found = result()
    table = render_table(found)

    for lead in found.leads:
        assert lead.name[:33] in table


def test_the_pipeline_is_deterministic():
    first = [lead.id for lead in result().leads]
    second = [lead.id for lead in result().leads]

    assert first == second


def test_an_agent_with_no_platforms_is_a_programming_error():
    with pytest.raises(ValueError, match="at least one place provider"):
        ProspectingAgent(places=[], settings=settings())
