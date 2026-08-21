"""The research demo is documented in the README, so a test keeps it honest."""

from __future__ import annotations

from agents.lead_research import demo
from agents.lead_research.models import FactStatus
from core.config import Settings


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def test_every_company_is_researched():
    assert len(demo.research_all(_settings())) == len(demo.COMPANIES)


def test_the_demo_exercises_every_verification_outcome():
    # A labelling system whose failure paths never run is one nobody should
    # rely on, so the demo is required to show all five.
    seen = {f.status for r in demo.research_all(_settings()) for f in r.facts}
    assert seen == set(FactStatus)


def test_no_flagged_claim_is_counted_as_verified():
    for result in demo.research_all(_settings()):
        for fact in result.verified:
            assert fact.status is FactStatus.VERIFIED


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "lead-research demo" in output
    assert "UNSRC" in output
