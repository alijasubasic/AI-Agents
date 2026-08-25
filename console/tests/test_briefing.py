"""Tests for turning a brief into speech, display and vault notes."""

from __future__ import annotations

from datetime import date

from agents.supervisor.models import (
    CodexFinding,
    DailyReport,
    Decision,
    DecisionKind,
    Review,
    Severity,
    TaskItem,
    TaskPriority,
    Verdict,
)
from console.briefing import (
    build_notes,
    build_overlay_state,
    build_utterances,
    spoken_date,
    spoken_number,
)
from console.models import Channel, Priority

DAY = date(2026, 3, 6)


def review(verdict: Verdict, **overrides) -> Review:
    findings = overrides.pop("findings", [])
    reasons = overrides.pop("reasons", [])
    base = {
        "id": "dec-1",
        "agent": "email-triage",
        "kind": DecisionKind.SEND_EMAIL,
        "subject": "Question about bulk pricing",
        "summary": "Asks for volume pricing.",
        "outbound_text": "Thanks for the enquiry.",
        "cost_usd": 0.0026,
    }
    return Review(
        decision=Decision(**{**base, **overrides}),
        verdict=verdict,
        reasons=reasons,
        findings=findings,
    )


def report(*reviews: Review, tasks: list[TaskItem] | None = None) -> DailyReport:
    return DailyReport(
        generated_for=DAY,
        covering=date(2026, 3, 5),
        reviews=list(reviews),
        tasks=tasks or [],
        total_cost_usd=sum(r.decision.cost_usd for r in reviews),
    )


# --- Speaking numbers and dates -----------------------------------------


def test_small_numbers_become_words():
    assert spoken_number(0) == "zero"
    assert spoken_number(17) == "seventeen"


def test_larger_numbers_stay_as_digits():
    assert spoken_number(42) == "42"


def test_dates_are_spoken_the_way_people_say_them():
    # Built by hand because %-d does not exist on Windows.
    assert spoken_date(date(2026, 3, 6)) == "Friday the 6th of March"
    assert spoken_date(date(2026, 3, 1)) == "Sunday the 1st of March"
    assert spoken_date(date(2026, 3, 2)) == "Monday the 2nd of March"
    assert spoken_date(date(2026, 3, 3)) == "Tuesday the 3rd of March"
    assert spoken_date(date(2026, 3, 11)) == "Wednesday the 11th of March"


# --- Utterances ---------------------------------------------------------


def test_the_briefing_opens_with_a_greeting_naming_the_day():
    lines = build_utterances(report())
    assert "Friday the 6th of March" in lines[0].to_speak


def test_spoken_and_displayed_wording_differ():
    # "7 approved · 8 held" is fine on screen and unintelligible aloud.
    summary = build_utterances(report(review(Verdict.APPROVED)))[1]

    assert "·" in summary.display_text
    assert "·" not in summary.to_speak
    assert "one decisions were reviewed" in summary.to_speak.lower()


def test_a_sentence_opening_with_a_number_is_capitalised():
    summary = build_utterances(report(review(Verdict.APPROVED)))[1]
    assert summary.to_speak.split()[0][0].isupper()


def test_every_blocked_decision_is_announced():
    lines = build_utterances(
        report(review(Verdict.BLOCKED, reasons=["A2 Honesty: repeats a claim"]))
    )
    blocked = [line for line in lines if line.priority is Priority.ALERT]

    assert len(blocked) == 1
    assert "Blocked:" in blocked[0].to_speak
    assert "A2 Honesty" in blocked[0].to_speak


def test_approved_decisions_are_not_read_out_one_by_one():
    # Reading seven approvals aloud trains the listener to stop paying
    # attention by the third, which is when the blocked one arrives.
    lines = build_utterances(report(*[review(Verdict.APPROVED, id=f"d{i}") for i in range(7)]))
    assert not any("d3" in (line.source_decision or "") for line in lines)


def test_urgent_tasks_are_named_and_the_rest_are_counted():
    tasks = [
        TaskItem(id="t1", title="Ring Alpina back", priority=TaskPriority.URGENT),
        TaskItem(id="t2", title="Check invoice", priority=TaskPriority.NORMAL),
        TaskItem(id="t3", title="Reply to Jana", priority=TaskPriority.NORMAL),
    ]
    spoken = " ".join(line.to_speak for line in build_utterances(report(tasks=tasks)))

    assert "Ring Alpina back" in spoken
    assert "two further tasks" in spoken
    assert "Check invoice" not in spoken


def test_the_cost_line_is_shown_but_never_spoken():
    cost = next(line for line in build_utterances(report()) if line.id == "cost")

    assert cost.channel is Channel.DISPLAY
    assert cost.to_speak == ""


def test_singular_and_plural_are_handled():
    one = " ".join(
        line.to_speak
        for line in build_utterances(report(tasks=[TaskItem(id="t1", title="One thing")]))
    )
    assert "is one further task" in one


# --- Overlay state ------------------------------------------------------


def test_the_overlay_orders_by_how_much_attention_is_needed():
    # A display sorted by time buries the two things worth looking at.
    state = build_overlay_state(
        report(
            review(Verdict.APPROVED, id="ok"),
            review(Verdict.BLOCKED, id="block"),
            review(Verdict.HOLD_FOR_HUMAN, id="hold"),
        )
    )
    assert [card.decision_id for card in state.cards] == ["block", "hold", "ok"]


def test_each_card_carries_the_verdict_tone_the_css_uses():
    state = build_overlay_state(
        report(review(Verdict.BLOCKED, id="a"), review(Verdict.APPROVED, id="b"))
    )
    assert [card.tone for card in state.cards] == ["block", "ok"]


def test_the_counts_match_the_report():
    state = build_overlay_state(
        report(
            review(Verdict.APPROVED, id="a"),
            review(Verdict.HOLD_FOR_HUMAN, id="b"),
            review(Verdict.BLOCKED, id="c"),
        )
    )
    assert (state.approved, state.held, state.blocked) == (1, 1, 1)
    assert state.total == 3
    assert state.needs_attention == 2


# --- Vault notes --------------------------------------------------------


def finding(article: str = "A2", title: str = "Honesty") -> CodexFinding:
    return CodexFinding(
        article=article,
        title=title,
        severity=Severity.BREACH,
        detail="repeats an unverified claim",
        verdict=Verdict.BLOCKED,
    )


def test_one_note_per_decision_plus_articles_plus_the_brief():
    notes = build_notes(report(review(Verdict.BLOCKED, findings=[finding()])))
    folders = [note.folder for note in notes]

    assert folders.count("Decisions") == 1
    assert folders.count("Codex") == 1
    assert folders.count("Briefs") == 1


def test_a_decision_note_links_to_its_agent_its_articles_and_the_brief():
    # The links are the point: Obsidian's backlinks then answer questions
    # nobody built a view for.
    (note, *_rest) = build_notes(report(review(Verdict.BLOCKED, findings=[finding()])))

    assert "Agent email-triage" in note.links
    assert "A2 Honesty" in note.links
    assert "2026-03-06 Brief" in note.links


def test_a_blocked_draft_is_recorded_as_not_sent():
    (note, *_rest) = build_notes(report(review(Verdict.BLOCKED)))
    assert "was **not** sent" in note.body


def test_an_approved_draft_is_recorded_as_sent():
    (note, *_rest) = build_notes(report(review(Verdict.APPROVED)))
    assert "was sent." in note.body


def test_a_decision_without_a_timestamp_omits_the_date_key():
    # Dataview treats `date: ""` as present-but-unparseable, which is worse
    # than an absent key.
    (note, *_rest) = build_notes(report(review(Verdict.APPROVED)))
    assert "date" not in note.frontmatter


def test_each_codex_article_gets_one_note_however_often_it_fired():
    notes = build_notes(
        report(
            review(Verdict.BLOCKED, id="a", findings=[finding()]),
            review(Verdict.BLOCKED, id="b", findings=[finding()]),
        )
    )
    assert [n.slug for n in notes if n.folder == "Codex"] == ["A2 Honesty"]


def test_the_brief_note_links_to_everything_needing_attention():
    brief = build_notes(
        report(
            review(Verdict.APPROVED, id="ok"),
            review(Verdict.BLOCKED, id="block"),
            review(Verdict.HOLD_FOR_HUMAN, id="hold"),
        )
    )[-1]

    assert set(brief.links) == {"block", "hold"}
    assert "ok" not in brief.links


def test_a_quiet_brief_says_so():
    brief = build_notes(report())[-1]
    assert "Nothing outstanding." in brief.body
