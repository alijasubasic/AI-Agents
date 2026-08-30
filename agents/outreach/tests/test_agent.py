"""Tests for the outreach agent end to end, on scripted drafts."""

from __future__ import annotations

import pytest

from agents.outreach.agent import OutreachAgent, candidate_address
from agents.outreach.fixtures import CAMPAIGN, SUPPRESSED
from agents.outreach.models import OutreachResult
from agents.outreach.providers import MockSender
from agents.outreach.scripted import DRAFTS, provider_for
from agents.outreach.suppression import MemorySuppressionList
from agents.prospecting.agent import ProspectingAgent
from agents.prospecting.fixtures import AREA
from agents.prospecting.models import ContactPoint, ContactStatus, Lead, Platform
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for as plan_provider
from core.config import Settings
from core.llm import MockProvider, text_response


def settings() -> Settings:
    return Settings(trace_enabled=False)


def leads() -> list[Lead]:
    return (
        ProspectingAgent(
            places=[
                MockPlaces(Platform.GOOGLE_MAPS),
                MockPlaces(Platform.OPENSTREETMAP),
                MockPlaces(Platform.DIRECTORY),
            ],
            pages=MockPages(),
            provider=plan_provider(AREA.what),
            settings=settings(),
        )
        .find(AREA)
        .leads
    )


def lead_named(name: str) -> Lead:
    return next(lead for lead in leads() if lead.name == name)


def build(lead: Lead, *, sender: MockSender | None = None, dry_run: bool = True) -> OutreachAgent:
    return OutreachAgent(
        provider=provider_for(lead.name),
        campaign=CAMPAIGN.model_copy(update={"dry_run": dry_run}),
        sender=sender,
        suppression=MemorySuppressionList(list(SUPPRESSED)),
        settings=settings(),
    )


def draft_for(name: str, **kwargs) -> OutreachResult:
    lead = lead_named(name)
    return build(lead, **kwargs).draft(lead)


# --- The draft ----------------------------------------------------------


def test_a_clean_lead_produces_a_sendable_draft():
    result = draft_for("Reiter Bedachungen GmbH")

    assert result.auto_send_allowed
    assert result.blockers == []
    assert result.recipient == "m.reiter@reiter-bedachungen.example"
    assert result.recipient_status is ContactStatus.CONFIRMED


def test_the_named_person_is_addressed_without_a_guessed_salutation():
    result = draft_for("Reiter Bedachungen GmbH")

    assert "Guten Tag Martin Reiter," in result.message
    assert "Herr" not in result.message


def test_the_footer_is_added_to_every_message():
    result = draft_for("Reiter Bedachungen GmbH")

    assert "Abmelden" in result.message
    assert "Impressum:" in result.message
    assert CAMPAIGN.sender.company in result.message


def test_the_message_says_where_the_address_came_from():
    result = draft_for("Reiter Bedachungen GmbH")

    assert "gefunden über" in result.message


def test_the_senders_phone_number_stays_out_of_the_body():
    """A phone number in outbound text trips codex A5 on every single send."""
    result = draft_for("Reiter Bedachungen GmbH")

    assert CAMPAIGN.sender.phone not in result.message


# --- What stops a send --------------------------------------------------


def test_a_suppressed_firm_is_drafted_but_flagged():
    result = draft_for("Nordwind Dachtechnik GmbH")

    assert not result.auto_send_allowed
    assert result.suppressed
    assert any("Sperrliste" in blocker for blocker in result.blockers)


def test_a_guessed_address_is_flagged_as_the_reason():
    result = draft_for("Dachdeckerei Sailer & Sohn")

    assert not result.auto_send_allowed
    assert result.recipient_status is ContactStatus.CONSTRUCTED


def test_an_invented_claim_is_carried_out_of_the_draft():
    result = draft_for("Alpenblick Dach & Fassade")

    assert result.unbacked_claims == ["über 200 sanierten Dächern im Raum München"]


def test_a_lead_with_no_address_costs_nothing():
    """No model call for a draft nobody could ever send."""
    lead = Lead(id="lead-99", name="Ohne Kontakt GmbH", city="München")
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = OutreachAgent(provider=provider, campaign=CAMPAIGN, settings=settings())

    result = agent.draft(lead)

    assert result.cost_usd == 0.0
    assert provider.remaining == 1
    assert result.blockers == [
        "keine E-Mail-Adresse vorhanden — Telefon oder Kontaktformular nutzen"
    ]


# --- Sending ------------------------------------------------------------


def test_nothing_is_sent_in_dry_run_even_when_approved():
    sender = MockSender()
    lead = lead_named("Reiter Bedachungen GmbH")
    agent = build(lead, sender=sender, dry_run=True)
    result = agent.draft(lead)

    assert agent.send(result, approved=True) is False
    assert sender.sent == []


def test_nothing_is_sent_without_approval():
    sender = MockSender()
    lead = lead_named("Reiter Bedachungen GmbH")
    agent = build(lead, sender=sender, dry_run=False)
    result = agent.draft(lead)

    assert agent.send(result, approved=False) is False
    assert sender.sent == []


def test_nothing_is_sent_when_the_policy_objected():
    sender = MockSender()
    lead = lead_named("Nordwind Dachtechnik GmbH")
    agent = build(lead, sender=sender, dry_run=False)
    result = agent.draft(lead)

    assert agent.send(result, approved=True) is False
    assert sender.sent == []


def test_all_three_yesses_together_send_exactly_one_email():
    sender = MockSender()
    lead = lead_named("Reiter Bedachungen GmbH")
    agent = build(lead, sender=sender, dry_run=False)
    result = agent.draft(lead)

    assert agent.send(result, approved=True) is True
    assert sender.recipients == ["m.reiter@reiter-bedachungen.example"]
    assert result.sent


def test_the_sent_message_carries_a_one_click_unsubscribe():
    sender = MockSender()
    lead = lead_named("Reiter Bedachungen GmbH")
    agent = build(lead, sender=sender, dry_run=False)
    agent.send(agent.draft(lead), approved=True)

    assert sender.sent[0].unsubscribe_mailto == CAMPAIGN.sender.email


# --- Recipient choice ---------------------------------------------------


def test_a_confirmed_personal_address_is_preferred():
    lead = lead_named("Reiter Bedachungen GmbH")
    chosen = candidate_address(lead)

    assert chosen is not None
    assert chosen.value == "m.reiter@reiter-bedachungen.example"


def test_an_invalid_address_is_never_the_candidate():
    lead = Lead(
        id="lead-98",
        name="Nur No-Reply GmbH",
        contacts=[
            ContactPoint(
                kind="email",
                value="noreply@x.example",
                status=ContactStatus.INVALID,
                platform=Platform.WEBSITE,
                source_url="https://x.example/impressum",
            )
        ],
    )

    assert candidate_address(lead) is None


def test_writing_to_a_company_twice_in_one_campaign_is_refused():
    """The case a merge that missed a duplicate produces: the same firm, twice."""
    lead = lead_named("Reiter Bedachungen GmbH")
    scripted = DRAFTS[lead.name].model_dump_json()
    agent = OutreachAgent(
        provider=MockProvider([text_response(scripted), text_response(scripted)]),
        campaign=CAMPAIGN,
        settings=settings(),
    )

    drafts = agent.draft_all([lead, lead])

    assert drafts[0].auto_send_allowed
    assert not drafts[1].auto_send_allowed
    assert any("bereits" in blocker for blocker in drafts[1].blockers)


@pytest.mark.parametrize(
    "company",
    ["Reiter Bedachungen GmbH", "Bauzentrum Isartal e.K."],
)
def test_every_scripted_draft_is_valid_against_the_schema(company: str):
    result = draft_for(company)

    assert result.email.subject
    assert result.email.body
