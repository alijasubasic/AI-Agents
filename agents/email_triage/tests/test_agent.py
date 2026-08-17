"""Tests for the triage agent end to end, on scripted model responses."""

from __future__ import annotations

import pytest

from agents.email_triage.agent import EmailTriageAgent, build_tools
from agents.email_triage.fixtures import INBOX, by_id
from agents.email_triage.models import Intent, Priority, Sentiment
from agents.email_triage.providers import MockCrm, MockMailbox
from agents.email_triage.scripted import provider_for
from core.config import Settings
from core.errors import StructuredOutputError
from core.llm import MockProvider, text_response


def settings() -> Settings:
    return Settings(trace_enabled=False)


def build(email_id: str) -> tuple[EmailTriageAgent, MockMailbox, MockCrm]:
    mailbox, crm = MockMailbox(), MockCrm()
    agent = EmailTriageAgent(
        provider=provider_for(email_id),
        crm=crm,
        mailbox=mailbox,
        settings=settings(),
    )
    return agent, mailbox, crm


# --- Classification -----------------------------------------------------


def test_a_routine_question_is_classified_and_cleared_for_auto_reply():
    agent, _, _ = build("msg-001")
    result = agent.triage(by_id("msg-001"))

    assert result.classification.intent is Intent.QUESTION
    assert result.classification.priority is Priority.NORMAL
    assert result.requires_human is False
    assert result.auto_send_allowed is True


def test_tasks_are_extracted_from_the_email():
    agent, _, _ = build("msg-001")
    result = agent.triage(by_id("msg-001"))

    descriptions = " ".join(t.description for t in result.classification.tasks)
    assert "volume pricing" in descriptions
    assert "lead time" in descriptions


def test_the_agent_looks_the_sender_up_in_the_crm_before_deciding():
    agent, _, crm = build("msg-002")
    agent.triage(by_id("msg-002"))

    assert crm.queries == ["alpina-ag.example"]


def test_cost_and_latency_are_attached_to_the_decision():
    agent, _, _ = build("msg-001")
    result = agent.triage(by_id("msg-001"))

    assert result.cost_usd > 0
    assert result.duration_ms >= 0


# --- Escalation ---------------------------------------------------------


def test_a_hostile_complaint_escalates_for_every_applicable_reason():
    agent, _, _ = build("msg-002")
    result = agent.triage(by_id("msg-002"))

    assert result.requires_human is True
    assert result.auto_send_allowed is False
    joined = " | ".join(result.escalation_reasons)
    assert "complaint" in joined
    assert "hostile" in joined
    assert "urgent" in joined
    assert "legal language" in joined


def test_a_refund_request_escalates_on_the_body_scan_alone():
    # The classification is confident and the intent is benign; only the word
    # "refund" in the body forces a human to look.
    agent, _, _ = build("msg-003")
    result = agent.triage(by_id("msg-003"))

    assert result.classification.confidence > 0.75
    assert result.classification.intent is not Intent.COMPLAINT
    assert result.requires_human is True
    assert result.escalation_reasons == ["body mentions money leaving the business"]


def test_a_vague_email_escalates_on_low_confidence():
    agent, _, _ = build("msg-006")
    result = agent.triage(by_id("msg-006"))

    assert result.classification.confidence < 0.75
    assert result.requires_human is True
    assert "low confidence" in result.escalation_reasons[0]


def test_a_scheduling_request_is_cleared():
    agent, _, _ = build("msg-004")
    result = agent.triage(by_id("msg-004"))

    assert result.classification.intent is Intent.SCHEDULING
    assert result.classification.sentiment is Sentiment.POSITIVE
    assert result.auto_send_allowed is True


# --- Sending ------------------------------------------------------------


def test_a_cleared_email_is_answered_and_labelled():
    agent, mailbox, _ = build("msg-001")
    result = agent.triage(by_id("msg-001"))

    assert agent.send_if_allowed(result) is True
    assert len(mailbox.sent) == 1
    assert mailbox.sent[0].email_id == "msg-001"
    assert mailbox.labels["msg-001"] == ["auto-answered"]


def test_an_escalated_email_is_never_sent():
    agent, mailbox, _ = build("msg-002")
    result = agent.triage(by_id("msg-002"))

    assert agent.send_if_allowed(result) is False
    assert mailbox.sent == []
    assert mailbox.labels["msg-002"] == ["needs-human"]


def test_spam_is_neither_answered_nor_escalated():
    agent, mailbox, _ = build("msg-005")
    result = agent.triage(by_id("msg-005"))

    # Nothing about spam needs a human, but replying would confirm the address
    # is live — so it is filed, not answered.
    assert result.requires_human is False
    assert result.auto_send_allowed is False
    assert agent.send_if_allowed(result) is False
    assert mailbox.sent == []


def test_a_halted_run_is_never_auto_sent():
    # One scripted response, but the step limit is set below what the run needs,
    # so the run halts. A halted run must not be trusted to answer anyone.
    mailbox = MockMailbox()
    agent = EmailTriageAgent(
        provider=provider_for("msg-001"),
        crm=MockCrm(),
        mailbox=mailbox,
        settings=Settings(trace_enabled=False, max_steps=1),
    )

    # The run halts before producing an answer, so there is no JSON to parse.
    # The failure is loud: nothing is silently treated as a valid classification.
    with pytest.raises(StructuredOutputError):
        agent.triage(by_id("msg-001"))
    assert mailbox.sent == []


# --- Tools --------------------------------------------------------------


def test_the_crm_tool_reports_a_known_account():
    registry = build_tools(MockCrm())
    output = registry.get("lookup_sender_account").run({"domain": "alpina-ag.example"})

    assert "Alpina AG" in output
    assert "key_account" in output
    assert "A-1044" in output


def test_the_crm_tool_handles_an_unknown_domain():
    registry = build_tools(MockCrm())
    output = registry.get("lookup_sender_account").run({"domain": "nobody.example"})

    assert "No CRM account" in output
    assert "new contact" in output


def test_the_tool_schema_is_advertised_to_the_model():
    registry = build_tools(MockCrm())
    (definition,) = registry.to_api_format()

    assert definition["name"] == "lookup_sender_account"
    assert "domain" in definition["input_schema"]["properties"]
    assert definition["description"]


# --- Inbox --------------------------------------------------------------


def test_triage_inbox_requires_a_mailbox():
    agent = EmailTriageAgent(
        provider=MockProvider([text_response("{}")]),
        crm=MockCrm(),
        settings=settings(),
    )
    with pytest.raises(ValueError, match="mailbox"):
        agent.triage_inbox()


def test_every_fixture_email_has_a_scripted_classification():
    # Guards against adding a fixture email and forgetting its script, which
    # would otherwise only surface as a confusing demo crash.
    for email in INBOX:
        assert provider_for(email.id) is not None
