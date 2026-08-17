"""Tests for the escalation policy.

This is the part of the agent that must behave identically every single run, so
it gets the densest test coverage in the package.
"""

from __future__ import annotations

import pydantic
import pytest

from agents.email_triage.models import Classification, Intent, Priority, Sentiment
from agents.email_triage.policy import DEFAULT_POLICY, EscalationPolicy


def classification(**overrides) -> Classification:
    """A confident, benign classification — the baseline that should NOT escalate."""
    base = {
        "priority": Priority.NORMAL,
        "intent": Intent.QUESTION,
        "sentiment": Sentiment.NEUTRAL,
        "confidence": 0.95,
        "summary": "Asks about lead times.",
        "tasks": [],
        "draft_reply": "Two weeks, currently.",
    }
    return Classification(**{**base, **overrides})


def test_a_confident_benign_email_does_not_escalate():
    assert DEFAULT_POLICY.evaluate(classification()) == []
    assert DEFAULT_POLICY.requires_human(classification()) is False


def test_low_confidence_escalates():
    reasons = DEFAULT_POLICY.evaluate(classification(confidence=0.4))
    assert len(reasons) == 1
    assert "low confidence" in reasons[0]


def test_confidence_exactly_at_the_threshold_does_not_escalate():
    # The threshold is a floor, not a trip wire: 0.75 is acceptable.
    assert DEFAULT_POLICY.evaluate(classification(confidence=0.75)) == []


def test_complaints_always_escalate_even_when_confident():
    reasons = DEFAULT_POLICY.evaluate(classification(intent=Intent.COMPLAINT, confidence=1.0))
    assert reasons == ["intent is complaint"]


def test_legal_intent_always_escalates():
    reasons = DEFAULT_POLICY.evaluate(classification(intent=Intent.LEGAL, confidence=1.0))
    assert reasons == ["intent is legal"]


def test_hostile_sentiment_escalates():
    reasons = DEFAULT_POLICY.evaluate(classification(sentiment=Sentiment.HOSTILE))
    assert reasons == ["sentiment is hostile"]


def test_urgent_priority_escalates():
    reasons = DEFAULT_POLICY.evaluate(classification(priority=Priority.URGENT))
    assert reasons == ["priority is urgent"]


def test_all_matching_reasons_are_reported_not_just_the_first():
    # A human opening an escalation should see everything that fired.
    reasons = DEFAULT_POLICY.evaluate(
        classification(
            priority=Priority.URGENT,
            intent=Intent.COMPLAINT,
            sentiment=Sentiment.HOSTILE,
            confidence=0.2,
        )
    )
    assert len(reasons) == 4


def test_body_scan_catches_legal_language_the_classifier_missed():
    # The classification looks entirely benign; only the raw text betrays it.
    reasons = DEFAULT_POLICY.evaluate(
        classification(), body="I have forwarded this to our attorney."
    )
    assert reasons == ["body mentions legal language"]


def test_body_scan_catches_refund_requests():
    reasons = DEFAULT_POLICY.evaluate(classification(), body="We would like a refund.")
    assert reasons == ["body mentions money leaving the business"]


def test_body_scan_catches_contract_termination():
    reasons = DEFAULT_POLICY.evaluate(
        classification(), body="We intend to cancel our contract at renewal."
    )
    assert reasons == ["body mentions contract termination"]


def test_body_scan_catches_public_exposure_risk():
    reasons = DEFAULT_POLICY.evaluate(
        classification(), body="A journalist has asked us about this."
    )
    assert reasons == ["body mentions public exposure risk"]


def test_body_scan_is_case_insensitive():
    assert DEFAULT_POLICY.evaluate(classification(), body="LAWSUIT") != []


def test_body_scan_does_not_fire_on_ordinary_text():
    body = "Thanks for the quick delivery, everything arrived in good condition."
    assert DEFAULT_POLICY.evaluate(classification(), body=body) == []


def test_body_scan_can_be_disabled():
    policy = EscalationPolicy(scan_body=False)
    assert policy.evaluate(classification(), body="I will sue you") == []


def test_threshold_is_configurable():
    strict = EscalationPolicy(min_confidence=0.99)
    assert strict.evaluate(classification(confidence=0.95)) != []

    lenient = EscalationPolicy(min_confidence=0.1)
    assert lenient.evaluate(classification(confidence=0.2)) == []


def test_escalation_intents_are_configurable():
    policy = EscalationPolicy(always_escalate_intents=frozenset({Intent.INVOICE}))
    assert policy.evaluate(classification(intent=Intent.INVOICE)) == ["intent is invoice"]
    # Complaint is no longer in the set, so it stops escalating on intent alone.
    assert policy.evaluate(classification(intent=Intent.COMPLAINT)) == []


def test_policy_is_immutable():
    # The policy is shared across agents; a caller must not be able to loosen it
    # for everyone by mutating the default instance.
    with pytest.raises(pydantic.ValidationError):
        DEFAULT_POLICY.min_confidence = 0.0
