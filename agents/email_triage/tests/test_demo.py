"""The agent demo is documented in the README, so a test keeps it honest."""

from __future__ import annotations

from agents.email_triage import demo
from agents.email_triage.fixtures import INBOX
from core.config import Settings


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def test_the_whole_fixture_inbox_is_triaged():
    outcomes = demo.triage_all(_settings())
    assert len(outcomes) == len(INBOX)


def test_the_demo_covers_both_routes():
    outcomes = demo.triage_all(_settings())

    sent = [r for r, was_sent in outcomes if was_sent]
    escalated = [r for r, _ in outcomes if r.requires_human]

    # A demo where everything escalates, or nothing does, demonstrates nothing.
    assert len(sent) >= 2
    assert len(escalated) >= 3


def test_spam_is_labelled_as_archived_not_as_escalated():
    # Three routes, not two. Spam reaches neither the sender nor a human, and
    # calling that "-> HUMAN" would misrepresent what the agent did.
    outcomes = demo.triage_all(_settings())
    labels = {r.email_id: demo.route_label(r, sent) for r, sent in outcomes}

    assert labels["msg-005"] == "ARCHIVED"
    assert labels["msg-002"] == "-> HUMAN"
    assert labels["msg-001"] == "AUTO-REPLY"


def test_no_escalated_email_was_answered():
    for result, was_sent in demo.triage_all(_settings()):
        if result.requires_human:
            assert was_sent is False


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "triaged" in output
    assert "escalated" in output
