"""Tests for the intake agent, including delegation to the booking agent."""

from __future__ import annotations

import pydantic
import pytest

from agents.calendar_booking.agent import CalendarBookingAgent
from agents.calendar_booking.fixtures import DANA, ORGANISER
from agents.calendar_booking.fixtures import REFERENCE_NOW as CALENDAR_NOW
from agents.calendar_booking.providers import MockCalendar
from agents.call_intake.agent import CallIntakeAgent, render_summary
from agents.call_intake.fixtures import TRANSCRIPTS, by_id
from agents.call_intake.models import CallIntent, Urgency
from agents.call_intake.policy import DEFAULT_POLICY, IntakePolicy
from agents.call_intake.scripted import EXTRACTIONS, provider_for
from core.config import Settings
from core.llm import MockProvider, text_response


def settings() -> Settings:
    return Settings(trace_enabled=False)


def booking_agent() -> tuple[CalendarBookingAgent, MockProvider]:
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = CalendarBookingAgent(
        provider=provider,
        calendar=MockCalendar(),
        organiser=ORGANISER,
        settings=settings(),
        now=CALENDAR_NOW,
    )
    return agent, provider


def build(call_id: str, *, with_booking: bool = True, policy: IntakePolicy = DEFAULT_POLICY):
    booking, booking_provider = booking_agent()
    agent = CallIntakeAgent(
        provider=provider_for(call_id),
        booking_agent=booking if with_booking else None,
        policy=policy,
        settings=settings(),
    )
    return agent, booking_provider


# --- Extraction ---------------------------------------------------------


def test_a_clean_call_is_extracted_and_cleared():
    agent, _ = build("call-001")
    result = agent.intake(by_id("call-001"))

    assert result.extraction.intent is CallIntent.NEW_ENQUIRY
    assert result.extraction.contact.name == "Dana Reyes"
    assert result.grounding_issues == []
    assert result.requires_human is False
    assert result.is_clean is True


def test_a_spelled_out_email_survives_the_grounding_check():
    agent, _ = build("call-001")
    result = agent.intake(by_id("call-001"))

    assert result.extraction.contact.email == "d.reyes@kestrel-systems.example"
    assert "email" not in {issue.field for issue in result.grounding_issues}


def test_a_phone_number_given_in_words_survives_the_grounding_check():
    agent, _ = build("call-002")
    result = agent.intake(by_id("call-002"))

    assert result.extraction.contact.phone
    assert "phone" not in {issue.field for issue in result.grounding_issues}


# --- The guard firing ---------------------------------------------------


def test_a_hallucinated_contact_detail_is_caught():
    agent, _ = build("call-003")
    result = agent.intake(by_id("call-003"))

    flagged = {issue.field for issue in result.grounding_issues}
    assert flagged == {"name", "company", "email"}
    assert result.requires_human is True
    assert result.is_clean is False


def test_the_summary_marks_unverified_details():
    agent, _ = build("call-003")
    result = agent.intake(by_id("call-003"))

    assert "not found in the transcript" in result.summary_markdown


# --- Escalation ---------------------------------------------------------


def test_a_complaint_reaches_a_human():
    agent, _ = build("call-002")
    result = agent.intake(by_id("call-002"))

    joined = " | ".join(result.escalation_reasons)
    assert "complaint" in joined
    assert "immediate" in joined


def test_a_poor_line_escalates_on_confidence():
    agent, _ = build("call-003")
    result = agent.intake(by_id("call-003"))

    assert result.extraction.confidence < 0.7
    assert any("low confidence" in reason for reason in result.escalation_reasons)


def test_spam_is_not_escalated():
    agent, _ = build("call-005")
    result = agent.intake(by_id("call-005"))

    assert result.extraction.intent is CallIntent.SPAM
    assert result.requires_human is False


# --- Injection ----------------------------------------------------------


def test_an_injection_attempt_is_detected_and_escalated():
    agent, _ = build("call-004")
    result = agent.intake(by_id("call-004"))

    assert result.requires_human is True
    assert any("prompt injection" in reason for reason in result.escalation_reasons)


def test_an_injection_attempt_never_reaches_the_booking_agent():
    agent, _ = build("call-004")
    result = agent.intake(by_id("call-004"))

    assert result.extraction.wants_meeting is True
    assert result.proposal is None


def test_injection_is_detected_before_the_model_is_consulted():
    assert EXTRACTIONS["call-004"].intent is not CallIntent.SPAM

    agent, _ = build("call-004")
    result = agent.intake(by_id("call-004"))
    assert result.escalation_reasons[0].startswith("possible prompt injection")


# --- Delegation ---------------------------------------------------------


def test_a_meeting_request_is_handed_to_the_booking_agent():
    agent, _ = build("call-001")
    result = agent.intake(by_id("call-001"))

    assert result.proposal is not None
    assert result.proposal.has_options


def test_delegation_does_not_call_a_model():
    agent, booking_provider = build("call-001")
    agent.intake(by_id("call-001"))

    assert booking_provider.calls == []
    assert booking_provider.remaining == 1


def test_the_proposed_times_suit_the_caller_time_zone():
    agent, _ = build("call-001")
    result = agent.intake(by_id("call-001"))

    for slot in result.proposal.slots:
        assert DANA.working_hours.covers(slot.start, slot.end)


def test_calls_without_a_meeting_request_are_not_delegated():
    agent, booking_provider = build("call-002")
    result = agent.intake(by_id("call-002"))

    assert result.proposal is None
    assert booking_provider.calls == []


def test_intake_works_without_a_booking_agent():
    agent, _ = build("call-001", with_booking=False)
    result = agent.intake(by_id("call-001"))

    assert result.proposal is None
    assert result.extraction.wants_meeting is True


# --- Summary ------------------------------------------------------------


def test_the_summary_names_missing_details_rather_than_omitting_them():
    agent, _ = build("call-005")
    result = agent.intake(by_id("call-005"))

    assert "_not given_" in result.summary_markdown


def test_the_summary_records_the_routing_decision():
    cleared, _ = build("call-001")
    escalated, _ = build("call-002")

    assert "Cleared" in cleared.intake(by_id("call-001")).summary_markdown
    assert "Needs a human" in escalated.intake(by_id("call-002")).summary_markdown


def test_the_summary_is_rendered_without_a_model():
    agent, _ = build("call-001")
    result = agent.intake(by_id("call-001"))

    assert render_summary(result) == result.summary_markdown


# --- Policy -------------------------------------------------------------


def test_policy_thresholds_are_configurable():
    strict = IntakePolicy(min_confidence=0.99)
    agent, _ = build("call-001", policy=strict)
    assert agent.intake(by_id("call-001")).requires_human is True


def test_policy_is_immutable():
    with pytest.raises(pydantic.ValidationError):
        DEFAULT_POLICY.min_confidence = 0.0


def test_every_fixture_transcript_has_a_scripted_extraction():
    for transcript in TRANSCRIPTS:
        assert provider_for(transcript.id) is not None

    with pytest.raises(KeyError):
        provider_for("call-999")


def test_urgency_is_reported():
    agent, _ = build("call-002")
    assert agent.intake(by_id("call-002")).extraction.urgency is Urgency.IMMEDIATE
