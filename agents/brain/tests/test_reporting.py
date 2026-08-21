"""Tests for the morning brief."""

from __future__ import annotations

from datetime import date

from agents.brain.models import (
    CodexFinding,
    Decision,
    DecisionKind,
    Review,
    Severity,
    TaskPriority,
    Verdict,
)
from agents.brain.reporting import (
    build_report,
    build_sheets,
    outbound_queue,
    render_markdown,
    tasks_from_reviews,
)

BRIEF_DAY = date(2026, 3, 6)


def review(verdict: Verdict, **overrides) -> Review:
    base = {
        "id": "d1",
        "agent": "email-triage",
        "kind": DecisionKind.SEND_EMAIL,
        "subject": "Re: your enquiry",
        "outbound_text": "A reply.",
        "recipient": "someone@example.test",
        "cost_usd": 0.01,
    }
    reasons = overrides.pop("reasons", [])
    findings = overrides.pop("findings", [])
    return Review(
        decision=Decision(**{**base, **overrides}),
        verdict=verdict,
        reasons=reasons,
        findings=findings,
    )


# --- Tasks --------------------------------------------------------------


def test_approved_decisions_produce_no_task():
    # An approved decision is finished. Listing it would bury the ones that
    # actually need someone.
    assert tasks_from_reviews([review(Verdict.APPROVED)]) == []


def test_held_and_blocked_decisions_each_produce_a_task():
    tasks = tasks_from_reviews(
        [review(Verdict.HOLD_FOR_HUMAN, id="a"), review(Verdict.BLOCKED, id="b")]
    )
    assert len(tasks) == 2


def test_a_blocked_task_says_unblock_and_a_held_one_says_review():
    (blocked,) = tasks_from_reviews([review(Verdict.BLOCKED)])
    (held,) = tasks_from_reviews([review(Verdict.HOLD_FOR_HUMAN)])

    assert blocked.title.startswith("Unblock")
    assert held.title.startswith("Review")


def test_urgent_wording_raises_the_priority():
    task = tasks_from_reviews([review(Verdict.HOLD_FOR_HUMAN, reasons=["intent is complaint"])])[0]
    assert task.priority is TaskPriority.URGENT


def test_a_block_without_urgent_wording_is_high_not_urgent():
    task = tasks_from_reviews([review(Verdict.BLOCKED, reasons=["cost ceiling"])])[0]
    assert task.priority is TaskPriority.HIGH


def test_tasks_are_sorted_with_the_most_urgent_first():
    tasks = tasks_from_reviews(
        [
            review(Verdict.HOLD_FOR_HUMAN, id="a", reasons=["nothing special"]),
            review(Verdict.HOLD_FOR_HUMAN, id="b", reasons=["urgent matter"]),
        ]
    )
    assert [t.priority for t in tasks] == [TaskPriority.URGENT, TaskPriority.NORMAL]


def test_a_task_records_where_it_came_from():
    task = tasks_from_reviews([review(Verdict.BLOCKED, id="dec-7")])[0]
    assert task.source_decision == "dec-7"
    assert task.origin_agent == "email-triage"


# --- Report -------------------------------------------------------------


def test_the_report_covers_the_day_before_by_default():
    report = build_report([], generated_for=BRIEF_DAY)
    assert report.covering == date(2026, 3, 5)


def test_the_report_counts_each_outcome():
    report = build_report(
        [
            review(Verdict.APPROVED, id="a"),
            review(Verdict.APPROVED, id="b"),
            review(Verdict.HOLD_FOR_HUMAN, id="c"),
            review(Verdict.BLOCKED, id="d"),
        ],
        generated_for=BRIEF_DAY,
    )

    assert len(report.approved) == 2
    assert len(report.held) == 1
    assert len(report.blocked) == 1
    assert report.autonomy_rate == 0.5


def test_an_empty_day_has_no_autonomy_rate_to_divide_by():
    assert build_report([], generated_for=BRIEF_DAY).autonomy_rate == 0.0


def test_cost_is_totalled_across_decisions():
    report = build_report(
        [review(Verdict.APPROVED, id="a", cost_usd=0.02), review(Verdict.BLOCKED, id="b")],
        generated_for=BRIEF_DAY,
    )
    assert report.total_cost_usd == 0.03


def test_the_outbound_queue_lists_only_what_actually_went_out():
    report = build_report(
        [
            review(Verdict.APPROVED, id="sent"),
            review(
                Verdict.APPROVED, id="internal", kind=DecisionKind.RECORD_CALL, outbound_text=""
            ),
            review(Verdict.HOLD_FOR_HUMAN, id="held"),
        ],
        generated_for=BRIEF_DAY,
    )

    assert [r.decision.id for r in outbound_queue(report)] == ["sent"]


# --- Markdown -----------------------------------------------------------


def test_the_brief_names_the_day_it_covers():
    text = render_markdown(build_report([], generated_for=BRIEF_DAY))
    assert "Friday 06 March 2026" in text
    assert "Thursday 05 March" in text


def test_a_quiet_day_says_so_rather_than_showing_an_empty_list():
    text = render_markdown(build_report([], generated_for=BRIEF_DAY))
    assert "Nothing outstanding" in text


def test_blocked_and_held_get_their_own_sections():
    text = render_markdown(
        build_report(
            [review(Verdict.BLOCKED, id="a"), review(Verdict.HOLD_FOR_HUMAN, id="b")],
            generated_for=BRIEF_DAY,
        )
    )
    assert "### Blocked" in text
    assert "### Held for review" in text


def test_the_codex_table_counts_each_article():
    finding = CodexFinding(
        article="A1",
        title="Human authority",
        severity=Severity.BREACH,
        detail="escalated",
        verdict=Verdict.HOLD_FOR_HUMAN,
    )
    text = render_markdown(
        build_report(
            [review(Verdict.HOLD_FOR_HUMAN, id=f"d{i}", findings=[finding]) for i in range(3)],
            generated_for=BRIEF_DAY,
        )
    )
    assert "| A1 Human authority | 3 |" in text


# --- Sheets -------------------------------------------------------------


def test_four_sheets_are_produced():
    sheets = build_sheets(build_report([review(Verdict.APPROVED)], generated_for=BRIEF_DAY))
    assert [s.name for s in sheets] == ["Summary", "Decisions", "Tasks today", "Codex findings"]


def test_every_row_matches_its_header_width():
    report = build_report(
        [review(Verdict.BLOCKED, id="a", reasons=["because"])], generated_for=BRIEF_DAY
    )
    for sheet in build_sheets(report):
        for row in sheet.rows:
            assert len(row) == len(sheet.columns)


def test_the_decisions_sheet_lists_every_review():
    report = build_report(
        [review(Verdict.APPROVED, id="a"), review(Verdict.BLOCKED, id="b")],
        generated_for=BRIEF_DAY,
    )
    decisions = next(s for s in build_sheets(report) if s.name == "Decisions")

    assert [row[0] for row in decisions.rows] == ["a", "b"]
    assert decisions.rows[1][4] == "blocked"


def test_sheet_names_become_filename_safe():
    sheets = build_sheets(build_report([], generated_for=BRIEF_DAY))
    assert {s.safe_name for s in sheets} == {
        "summary",
        "decisions",
        "tasks-today",
        "codex-findings",
    }
