"""Tests for the supervisor running a whole lead campaign.

The individual guards are tested where they live. What is tested here is that
they are actually wired together: that a draft the policy objected to reaches
the codex as an escalation, that an approval is required before anything is
sent, and that dry run beats an approval.
"""

from __future__ import annotations

from agents.outreach.fixtures import CAMPAIGN, SUPPRESSED
from agents.outreach.providers import MockSender
from agents.outreach.scripted import provider_for as draft_provider
from agents.outreach.suppression import MemorySuppressionList
from agents.prospecting.fixtures import AREA
from agents.prospecting.models import Platform
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for as plan_provider
from agents.supervisor.campaign import LeadCampaign, lead_sheet, outreach_sheet, render_summary
from agents.supervisor.models import DecisionKind, Verdict
from agents.supervisor.scripted import judge_provider
from core.config import Settings


def settings() -> Settings:
    return Settings(trace_enabled=False)


def campaign(*, dry_run: bool = True, sender: MockSender | None = None) -> LeadCampaign:
    return LeadCampaign(
        area=AREA,
        campaign=CAMPAIGN.model_copy(update={"dry_run": dry_run}),
        places=[
            MockPlaces(Platform.GOOGLE_MAPS),
            MockPlaces(Platform.OPENSTREETMAP),
            MockPlaces(Platform.DIRECTORY),
        ],
        pages=MockPages(),
        planner=plan_provider(AREA.what),
        draft_provider=lambda lead: draft_provider(lead.name),
        judge=judge_provider,
        sender=sender,
        suppression=MemorySuppressionList(list(SUPPRESSED)),
        settings=settings(),
    )


def verdicts(result) -> dict[str, Verdict]:
    return {review.decision.subject: review.verdict for review in result.outreach_reviews}


# --- The chain ----------------------------------------------------------


def test_both_agents_run_and_both_are_reviewed():
    result = campaign().run()
    agents = {review.decision.agent for review in result.reviews}

    assert agents == {"prospecting", "outreach"}


def test_one_decision_per_business_plus_the_search_itself():
    result = campaign().run()

    assert len(result.reviews) == len(result.drafts) + 1


def test_the_search_itself_is_internal_and_approved():
    result = campaign().run()
    search = next(r for r in result.reviews if r.decision.kind is DecisionKind.COLLECT_LEADS)

    assert search.verdict is Verdict.APPROVED
    assert search.decision.outbound_text == ""


def test_a_clean_lead_is_approved():
    result = campaign().run()

    assert verdicts(result)["Erstkontakt: Reiter Bedachungen GmbH"] is Verdict.APPROVED


def test_a_guessed_address_is_blocked_by_the_codex():
    result = campaign().run()
    review = next(r for r in result.outreach_reviews if "Sailer" in r.decision.subject)

    assert review.verdict is Verdict.BLOCKED
    assert {finding.article for finding in review.findings} >= {"A4", "A9"}


def test_an_opt_out_survives_a_perfectly_written_email():
    result = campaign().run()
    review = next(r for r in result.outreach_reviews if "Nordwind" in r.decision.subject)

    assert review.verdict is Verdict.BLOCKED
    assert any(finding.article == "A10" for finding in review.findings)


def test_an_invented_claim_repeated_to_a_prospect_is_blocked():
    """The chain closing: outreach flagged the claim, and A2 finds it in the text."""
    result = campaign().run()
    review = next(r for r in result.outreach_reviews if "Alpenblick" in r.decision.subject)

    assert review.verdict is Verdict.BLOCKED
    assert any(finding.article == "A2" for finding in review.findings)


def test_every_cold_decision_carries_the_source_of_its_address():
    result = campaign().run()

    for review in result.outreach_reviews:
        decision = review.decision
        if decision.recipient_verified:
            assert decision.contact_source


# --- Sending ------------------------------------------------------------


def test_a_dry_run_sends_nothing_however_many_approvals_there_are():
    sender = MockSender()
    result = campaign(dry_run=True, sender=sender).run()

    assert result.approved
    assert result.sent_to == []
    assert sender.sent == []


def test_with_dry_run_off_exactly_the_approved_ones_go():
    sender = MockSender()
    result = campaign(dry_run=False, sender=sender).run()

    approved_companies = {review.decision.subject for review in result.approved}

    assert len(sender.sent) == len(approved_companies)
    assert set(result.sent_to) == {message.to for message in sender.sent}
    assert "i.brandl@nordwind-dachtechnik.example" not in result.sent_to


def test_no_mail_sender_means_nothing_can_be_sent():
    result = campaign(dry_run=False, sender=None).run()

    assert result.sent_to == []


# --- Output -------------------------------------------------------------


def test_the_lead_sheet_has_one_row_per_business():
    result = campaign().run()
    sheet = lead_sheet(result)

    assert len(sheet.rows) == len(result.leads)
    assert "E-Mail" in sheet.columns
    assert "Telefon" in sheet.columns


def test_the_outreach_sheet_records_the_verdict_and_the_reasons():
    result = campaign().run()
    rows = {row[0]: row for row in outreach_sheet(result).rows}
    blocked = rows["Dachdeckerei Sailer & Sohn"]

    assert blocked[4] == "blocked"
    assert blocked[5] == "nein"
    assert blocked[6]


def test_the_summary_reports_what_happened():
    result = campaign().run()
    summary = render_summary(result)

    assert "Betriebe:" in summary
    assert "Testlauf" in summary


def test_a_campaign_with_no_outreach_step_only_searches():
    searcher = LeadCampaign(
        area=AREA,
        campaign=CAMPAIGN,
        places=[MockPlaces(Platform.GOOGLE_MAPS)],
        pages=MockPages(),
        planner=plan_provider(AREA.what),
        settings=settings(),
    )
    result = searcher.run()

    assert result.leads
    assert result.drafts == []
    assert len(result.reviews) == 1


def test_the_whole_campaign_is_deterministic():
    first = [review.verdict for review in campaign().run().reviews]
    second = [review.verdict for review in campaign().run().reviews]

    assert first == second
