"""Tests for running every agent together under supervision.

This is the file that checks the system behaves as a system: that each agent's
conclusions survive the trip into a `Decision`, and that the chains between
agents actually close.
"""

from __future__ import annotations

from agents.brain import demo
from agents.brain.models import Verdict
from agents.brain.pipeline import run_all
from core.config import Settings


def settings() -> Settings:
    return Settings(trace_enabled=False)


def by_id(reviews, decision_id):
    return next(r for r in reviews if r.decision.id == decision_id)


# --- Everything runs ----------------------------------------------------


def test_every_agent_contributes_decisions():
    agents = {d.agent for d in run_all(settings())}
    assert agents == {"email-triage", "call-intake", "lead-research"}


def test_the_pipeline_is_deterministic():
    first = [d.id for d in run_all(settings())]
    second = [d.id for d in run_all(settings())]
    assert first == second


def test_every_decision_has_a_unique_id():
    ids = [d.id for d in run_all(settings())]
    assert len(ids) == len(set(ids))


# --- The chains close ---------------------------------------------------


def test_an_unsourced_research_claim_is_blocked_from_reaching_a_prospect():
    # The chain: lead-research labels the revenue figure UNSOURCED, an outreach
    # draft repeats it to the prospect, and article A2 stops the send. No agent
    # in that chain noticed anything wrong.
    report = demo.run(settings())
    review = by_id(report.reviews, "dec-outreach-kestrel-systems")

    assert review.verdict is Verdict.BLOCKED
    assert any(f.article == "A2" for f in review.findings)
    assert "8M ARR" in " ".join(review.reasons)


def test_a_follow_up_to_a_hallucinated_address_is_blocked():
    # call-intake established the caller never said that address; the codex
    # refuses to let anything be sent to it.
    report = demo.run(settings())
    review = by_id(report.reviews, "dec-followup-call-003")

    assert review.verdict is Verdict.BLOCKED
    assert any(f.article == "A4" for f in review.findings)


def test_a_follow_up_to_a_confirmed_address_goes_out():
    report = demo.run(settings())
    review = by_id(report.reviews, "dec-followup-call-001")

    assert review.verdict is Verdict.APPROVED


def test_pressure_selling_is_held_not_blocked():
    # A draft that needs an edit is held for a person; only dishonesty and
    # unconfirmed recipients are destroyed outright.
    report = demo.run(settings())
    review = by_id(report.reviews, "dec-outreach-halvard-marine")

    assert review.verdict is Verdict.HOLD_FOR_HUMAN
    assert {f.article for f in review.findings} == {"A3", "A6"}


def test_every_escalation_from_a_specialist_survives_supervision():
    # The property the whole design rests on, checked against real agent output
    # rather than a constructed decision.
    report = demo.run(settings())
    for review in report.reviews:
        if review.decision.requires_human:
            assert review.verdict is not Verdict.APPROVED


def test_the_reviewer_catches_something_the_codex_missed():
    # The scheduling reply commits to a specific slot before anyone checked the
    # calendar. No rule can see that; the model can.
    report = demo.run(settings())
    review = by_id(report.reviews, "dec-email-msg-004")

    assert review.findings == []
    assert review.verdict is Verdict.HOLD_FOR_HUMAN
    assert any("reviewer:" in reason for reason in review.reasons)


# --- The brief ----------------------------------------------------------


def test_the_brief_accounts_for_every_decision():
    report = demo.run(settings())
    assert len(report.approved) + len(report.held) + len(report.blocked) == len(report.reviews)


def test_nothing_approved_appears_as_a_task():
    report = demo.run(settings())
    approved_ids = {r.decision.id for r in report.approved}
    task_sources = {t.source_decision for t in report.tasks}

    assert approved_ids.isdisjoint(task_sources)


def test_every_unfinished_decision_becomes_a_task():
    report = demo.run(settings())
    unfinished = {r.decision.id for r in report.held + report.blocked}

    assert {t.source_decision for t in report.tasks} == unfinished


def test_the_scripted_judgements_match_what_the_supervisor_asks_for():
    # If the mock ran short the review would raise, and if it ran long this
    # would catch the drift. Either way the fixture cannot quietly rot.
    report = demo.run(settings())
    judged = [r for r in report.reviews if r.judgement is not None]
    blocked = [r for r in report.reviews if r.verdict is Verdict.BLOCKED]

    assert len(judged) == len(report.reviews) - len(blocked)


def test_the_demo_writes_a_brief_and_a_spreadsheet(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "OUTPUT_DIR", tmp_path)
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    assert (tmp_path / "2026-03-06-brief.md").exists()
    csvs = sorted(p.name for p in (tmp_path / "2026-03-06").glob("*.csv"))
    assert csvs == [
        "01-summary.csv",
        "02-decisions.csv",
        "03-tasks-today.csv",
        "04-codex-findings.csv",
    ]
