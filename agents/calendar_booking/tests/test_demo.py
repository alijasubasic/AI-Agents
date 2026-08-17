"""The booking demo is documented in the README, so a test keeps it honest."""

from __future__ import annotations

from agents.calendar_booking import demo
from agents.calendar_booking.fixtures import ORGANISER
from core.config import Settings


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def test_the_internal_scenario_proposes_and_books():
    proposal, booking = demo.run_scenario("internal", settings=_settings())

    assert proposal.has_options
    assert booking is not None
    assert booking.booked is True


def test_the_transatlantic_scenario_only_offers_the_overlap():
    proposal, _ = demo.run_scenario("transatlantic", settings=_settings())

    assert proposal.has_options
    for slot in proposal.slots:
        # 09:00–17:00 in New York, seen from Berlin, is an afternoon window.
        berlin_hour = slot.start.astimezone(ORGANISER.working_hours.zone).hour
        assert berlin_hour >= 13


def test_the_impossible_scenario_offers_nothing_and_books_nothing():
    proposal, booking = demo.run_scenario("impossible", settings=_settings())

    assert proposal.slots == []
    assert booking is None


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "calendar-booking demo" in output
    assert "not by the model" in output
