"""The intake demo is documented in the README, so a test keeps it honest."""

from __future__ import annotations

from agents.call_intake import demo
from agents.call_intake.fixtures import TRANSCRIPTS
from core.config import Settings


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def test_every_transcript_is_processed():
    assert len(demo.intake_all(_settings())) == len(TRANSCRIPTS)


def test_the_demo_shows_each_outcome_at_least_once():
    results = demo.intake_all(_settings())

    assert any(r.is_clean for r in results)
    assert any(r.grounding_issues for r in results)
    assert any(r.proposal is not None for r in results)
    assert any(any("injection" in reason for reason in r.escalation_reasons) for r in results)


def test_an_injection_call_is_never_sent_to_the_booking_agent():
    for result in demo.intake_all(_settings()):
        if any("injection" in reason for reason in result.escalation_reasons):
            assert result.proposal is None


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "call-intake demo" in output
    assert "NOT SAID BY THE CALLER" in output
