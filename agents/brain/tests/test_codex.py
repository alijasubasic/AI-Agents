"""Tests for the executable codex.

The codex is what makes the supervisor's principles real rather than
aspirational, so every article gets a test that fires it and one that does not.
"""

from __future__ import annotations

from agents.brain.codex import (
    MAX_DECISION_COST_USD,
    apply_codex,
    article_1_human_authority,
    article_2_honesty,
    article_3_no_unbacked_commitments,
    article_4_confirmed_recipient,
    article_5_data_minimisation,
    article_6_fair_dealing,
    article_7_cost_discipline,
    article_8_auditability,
    codex_verdict,
)
from agents.brain.models import Decision, DecisionKind, Severity, Verdict


def decision(**overrides) -> Decision:
    """A clean outbound email that breaches nothing."""
    base = {
        "id": "d1",
        "agent": "email-triage",
        "kind": DecisionKind.SEND_EMAIL,
        "subject": "Re: your enquiry",
        "outbound_text": "Thanks for getting in touch. I will look into it and reply.",
        "recipient": "someone@example.test",
        "recipient_verified": True,
        "trace_ref": "msg-1",
        "cost_usd": 0.01,
    }
    return Decision(**{**base, **overrides})


def test_a_clean_decision_breaches_nothing():
    assert apply_codex(decision()) == []
    assert codex_verdict([]) is Verdict.APPROVED


# --- A1 human authority -------------------------------------------------


def test_an_escalated_decision_can_never_be_approved():
    findings = article_1_human_authority(
        decision(requires_human=True, escalation_reasons=["sentiment is hostile"])
    )
    assert len(findings) == 1
    assert findings[0].verdict is Verdict.HOLD_FOR_HUMAN
    assert "hostile" in findings[0].detail


def test_an_escalation_with_no_recorded_reason_still_holds():
    findings = article_1_human_authority(decision(requires_human=True))
    assert findings[0].verdict is Verdict.HOLD_FOR_HUMAN
    assert "no reason recorded" in findings[0].detail


def test_a_decision_nobody_escalated_passes_article_one():
    assert article_1_human_authority(decision()) == []


# --- A2 honesty ---------------------------------------------------------


def test_repeating_an_unverified_claim_to_a_customer_is_blocked():
    findings = article_2_honesty(
        decision(
            outbound_text="Since you are at approximately $8M ARR, our line suits you.",
            unverified_claims=["approximately $8M ARR"],
        )
    )
    assert findings[0].verdict is Verdict.BLOCKED
    assert findings[0].severity is Severity.BREACH


def test_holding_an_unverified_claim_internally_is_fine():
    # Nothing goes out, so there is nobody to mislead.
    findings = article_2_honesty(
        decision(
            kind=DecisionKind.PUBLISH_RESEARCH,
            outbound_text="",
            unverified_claims=["approximately $8M ARR"],
        )
    )
    assert findings == []


def test_an_unverified_claim_that_stays_out_of_the_draft_is_fine():
    findings = article_2_honesty(
        decision(
            outbound_text="Happy to walk through the range whenever suits.",
            unverified_claims=["approximately $8M ARR"],
        )
    )
    assert findings == []


# --- A3 commitments -----------------------------------------------------


def test_a_guarantee_is_held():
    findings = article_3_no_unbacked_commitments(
        decision(outbound_text="We guarantee delivery within a week.")
    )
    assert findings[0].verdict is Verdict.HOLD_FOR_HUMAN
    assert "a guarantee" in findings[0].detail


def test_a_price_is_held():
    assert article_3_no_unbacked_commitments(decision(outbound_text="It is $499.")) != []


def test_a_discount_is_held():
    assert article_3_no_unbacked_commitments(decision(outbound_text="A 20% discount.")) != []


def test_commitments_in_internal_records_are_not_checked():
    # Article 3 is about what the company promises the outside world.
    findings = article_3_no_unbacked_commitments(
        decision(kind=DecisionKind.RECORD_CALL, outbound_text="We guarantee it.")
    )
    assert findings == []


def test_every_commitment_type_is_named_once():
    findings = article_3_no_unbacked_commitments(
        decision(outbound_text="We guarantee it and we guarantee it again.")
    )
    assert findings[0].detail.count("a guarantee") == 1


# --- A4 recipient -------------------------------------------------------


def test_writing_to_an_unconfirmed_address_is_blocked():
    findings = article_4_confirmed_recipient(
        decision(recipient="invented@example.test", recipient_verified=False)
    )
    assert findings[0].verdict is Verdict.BLOCKED


def test_a_decision_where_the_question_does_not_arise_passes():
    # None means "not applicable", which is different from "checked and failed".
    assert article_4_confirmed_recipient(decision(recipient_verified=None)) == []


def test_an_internal_decision_needs_no_recipient_check():
    findings = article_4_confirmed_recipient(
        decision(kind=DecisionKind.RECORD_CALL, recipient_verified=False)
    )
    assert findings == []


# --- A5 data minimisation ----------------------------------------------


def test_another_persons_address_in_a_message_is_held():
    findings = article_5_data_minimisation(
        decision(outbound_text="Ask colleague@other.test about it.")
    )
    assert findings[0].verdict is Verdict.HOLD_FOR_HUMAN


def test_the_recipients_own_address_is_not_a_leak():
    findings = article_5_data_minimisation(
        decision(
            recipient="someone@example.test",
            outbound_text="Confirming we will use someone@example.test.",
        )
    )
    assert findings == []


def test_a_phone_number_in_a_message_is_held():
    assert article_5_data_minimisation(decision(outbound_text="Call 0171 442 8819.")) != []


# --- A6 fair dealing ----------------------------------------------------


def test_pressure_selling_is_flagged():
    findings = article_6_fair_dealing(decision(outbound_text="Act now - this offer expires soon."))
    assert findings[0].severity is Severity.BREACH
    assert "urgency pressure" in findings[0].detail
    assert "artificial scarcity" in findings[0].detail


def test_ordinary_wording_is_not_pressure():
    assert article_6_fair_dealing(decision()) == []


# --- A7 and A8 ----------------------------------------------------------


def test_an_expensive_decision_is_held():
    findings = article_7_cost_discipline(decision(cost_usd=MAX_DECISION_COST_USD + 0.01))
    assert findings[0].verdict is Verdict.HOLD_FOR_HUMAN


def test_a_decision_exactly_at_the_ceiling_passes():
    assert article_7_cost_discipline(decision(cost_usd=MAX_DECISION_COST_USD)) == []


def test_a_decision_with_no_trace_is_held():
    findings = article_8_auditability(decision(trace_ref=None))
    assert findings[0].verdict is Verdict.HOLD_FOR_HUMAN
    assert findings[0].severity is Severity.NOTE


# --- Combination --------------------------------------------------------


def test_findings_accumulate_rather_than_short_circuiting():
    # A reviewer should see everything wrong at once, not the first thing
    # that happened to be checked.
    findings = apply_codex(
        decision(
            requires_human=True,
            outbound_text="We guarantee it - act now! Call 0171 442 8819.",
            recipient_verified=False,
            cost_usd=9.99,
            trace_ref=None,
        )
    )
    assert {f.article for f in findings} == {"A1", "A3", "A4", "A5", "A6", "A7", "A8"}


def test_the_verdict_is_the_strictest_article():
    findings = apply_codex(decision(requires_human=True, recipient_verified=False))
    assert codex_verdict(findings) is Verdict.BLOCKED


def test_an_empty_finding_list_approves():
    assert codex_verdict([]) is Verdict.APPROVED
