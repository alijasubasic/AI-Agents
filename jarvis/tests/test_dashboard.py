"""Tests for the panels, the page and the capture route.

The page is asserted as a string rather than driven in a browser. That is a
real limit and worth naming: these tests prove the markup contains what it
should and nothing it shouldn't, not that it *looks* right. The properties
worth testing here are security properties, and those survive the translation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.supervisor import demo as supervisor_demo
from console.briefing import build_overlay_state
from console.chat_demo import build_session
from console.models import VaultNote
from console.tasks import Conversation, Speaker, Task, TaskStatus
from console.vault import MemoryVault, ObsidianVault
from core.config import Settings
from jarvis.capture import FOLDER, MAX_BODY, CaptureRefused, build_note, capture
from jarvis.diagnostics import measure
from jarvis.page import embed_json, render_dashboard
from jarvis.panels import analytics_panel, build, fleet_panel, sessions_panel
from telemetry.fixtures import demo_telemetry
from telemetry.models import Telemetry


def settings() -> Settings:
    return Settings(trace_enabled=False)


@pytest.fixture(scope="module")
def overlay():
    return build_overlay_state(supervisor_demo.run(Settings(trace_enabled=False)))


@pytest.fixture(scope="module")
def diagnostics():
    # The eval suite is exercised by its own harness; running it again here
    # would add two seconds per test file to prove nothing new.
    return measure(Settings(trace_enabled=False), run_evals=False)


@pytest.fixture
def dashboard(overlay, diagnostics):
    return build(
        state=overlay,
        conversation=Conversation(id="test"),
        telemetry=demo_telemetry(),
        diagnostics=diagnostics,
        mode="mock",
        model="claude-opus-5",
        capture_target="vault",
    )


# --- Panels --------------------------------------------------------------


def test_the_fleet_shows_every_agent_even_with_no_tasks():
    members = fleet_panel(Conversation(id="test"))

    assert len(members) == 8
    assert all(member.tone == "dim" for member in members)
    assert {"lead-research", "knowledge-base", "calendar-booking"} == {
        member.name for member in members if member.reachable
    }


def test_the_fleet_picks_up_this_session_s_tasks():
    conversation = Conversation(id="test")
    conversation.tasks.append(
        Task(id="t1", request="x", agent="lead-research", status=TaskStatus.DONE)
    )
    conversation.tasks.append(
        Task(id="t2", request="y", agent="lead-research", status=TaskStatus.ESCALATED)
    )

    member = next(m for m in fleet_panel(conversation) if m.name == "lead-research")

    assert member.tasks == 2
    # The tone follows the most recent task, not the best one.
    assert member.tone == "hold"


def test_the_fleet_is_not_joined_to_live_sessions():
    """The join that is deliberately not made.

    These agents run in this process. The live sessions are Claude Code
    transcripts that have nothing to do with them, and wiring one to the other
    would make an agent card flicker because a terminal opened elsewhere.
    """
    busy = demo_telemetry()
    assert busy.live, "the fixture has live sessions"

    members = fleet_panel(Conversation(id="test"))

    assert all(member.tone == "dim" for member in members)


def test_sessions_carry_no_transcript_text():
    rows = sessions_panel(demo_telemetry())

    assert rows
    for row in rows:
        assert row.doing.startswith(("running ", "delegating to ", "waiting", "working", "idle"))


def test_the_heatmap_is_normalised_server_side():
    analytics = analytics_panel(demo_telemetry())

    assert len(analytics.days) == 30
    assert all(0.0 <= cell.level <= 1.0 for cell in analytics.days)
    # Any day with activity is visible, however small next to the peak.
    assert all(cell.level >= 0.14 for cell in analytics.days if cell.messages)
    assert all(cell.level == 0.0 for cell in analytics.days if not cell.messages)


def test_an_empty_telemetry_still_produces_a_panel():
    analytics = analytics_panel(Telemetry(real=True, source="nowhere"))

    assert analytics.days == []
    assert analytics.busiest_hour is None
    assert analytics.peak_hourly == 0


def test_fixtures_are_announced_in_the_subheading(overlay, diagnostics):
    dashboard = build(
        state=overlay,
        conversation=Conversation(id="test"),
        telemetry=demo_telemetry(),
        diagnostics=diagnostics,
    )
    assert "fixtures" in dashboard.subheading


def test_a_real_scan_is_announced_as_real(overlay, diagnostics):
    dashboard = build(
        state=overlay,
        conversation=Conversation(id="test"),
        telemetry=Telemetry(real=True, source="/somewhere", window_days=30),
        diagnostics=diagnostics,
    )
    assert "fixtures" not in dashboard.subheading
    assert "/somewhere" in dashboard.subheading


# --- The page ------------------------------------------------------------


def test_the_page_is_self_contained(dashboard):
    page = render_dashboard(dashboard)

    assert page.lower().startswith("<!doctype html>")
    assert "https://" not in page
    assert "cdn." not in page
    assert "<script src" not in page


def test_the_page_has_no_inline_event_handlers(dashboard):
    """The improvement over the earlier console.

    `onclick="answer('${id}', …)"` nests data inside a JavaScript string inside
    an HTML attribute. Two layers of quoting is one too many, and an apostrophe
    in the wrong field escapes both. Every control here carries `data-` values
    read by one delegated listener.
    """
    page = render_dashboard(dashboard)

    for handler in ("onclick=", "onkeydown=", "onchange=", "onsubmit=", "onload="):
        assert handler not in page


def test_the_page_never_builds_markup_from_data(dashboard):
    page = render_dashboard(dashboard)
    assert "innerHTML" not in page


def test_a_script_tag_in_a_task_cannot_close_the_bootstrap_block(overlay, diagnostics):
    """The hole `embed_json` exists for, asserted on this page too.

    `json.dumps` escapes quotes but not angle brackets, so a task containing
    the literal `</script>` ended the block early and everything after it was
    parsed as markup.
    """
    conversation = Conversation(id="test")
    conversation.say(Speaker.OPERATOR, "</script><img src=x onerror=alert(1)>")

    page = render_dashboard(
        build(
            state=overlay,
            conversation=conversation,
            telemetry=demo_telemetry(),
            diagnostics=diagnostics,
        )
    )

    assert "</script><img" not in page
    assert "\\u003c/script\\u003e" in page
    # Exactly the three script blocks the template defines — bootstrap, the
    # sphere, the app — and no more. A fourth means data closed one early.
    assert page.count("<script>") == 3


def test_embed_json_round_trips():
    import json

    payload = {"text": "<b>a & b</b>", "n": 1}
    assert json.loads(embed_json(payload)) == payload


def test_the_capture_target_is_escaped_into_the_page(overlay, diagnostics):
    dashboard = build(
        state=overlay,
        conversation=Conversation(id="test"),
        telemetry=demo_telemetry(),
        diagnostics=diagnostics,
        capture_target='<img src=x onerror="alert(1)">',
    )

    page = render_dashboard(dashboard)

    assert "<img src=x" not in page
    assert "&lt;img" in page


def test_the_page_says_when_no_vault_is_configured(overlay, diagnostics):
    dashboard = build(
        state=overlay,
        conversation=Conversation(id="test"),
        telemetry=demo_telemetry(),
        diagnostics=diagnostics,
        capture_target="",
    )
    assert "no vault configured" in render_dashboard(dashboard)


def test_the_whole_dashboard_serialises_to_json(dashboard):
    payload = dashboard.model_dump(mode="json")
    assert set(payload) >= {"fleet", "sessions", "analytics", "checks", "turns", "questions"}


# --- Diagnostics ---------------------------------------------------------


def test_diagnostics_report_the_guardrails_not_the_machine():
    checks = {check.label for check in measure(settings(), run_evals=False).checks}

    assert {"Codex articles", "Step ceiling", "Run deadline", "Cost budget"} <= checks
    assert not {"CPU", "Memory", "Uptime"} & checks


def test_a_skipped_eval_run_is_said_out_loud():
    diagnostics = measure(settings(), run_evals=False)

    assert diagnostics.evals_run is False
    assert any(check.value == "not run" for check in diagnostics.checks)


def test_live_mode_is_flagged_on_the_panel():
    live = Settings(mode="live", api_key="x", trace_enabled=False)
    check = next(c for c in measure(live, run_evals=False).checks if c.label == "Mode")

    assert check.value == "live"
    assert check.tone == "hold"


def test_the_eval_suite_is_actually_run_when_asked():
    """Slow — a couple of seconds — which is why the server does it once."""
    diagnostics = measure(settings(), run_evals=True)
    suite = next(check for check in diagnostics.checks if check.label == "Eval suite")

    assert diagnostics.evals_run is True
    assert suite.value.endswith("%")


# --- Quick capture -------------------------------------------------------


def test_a_capture_lands_in_one_fixed_folder():
    note = build_note("A thought", "the body")

    assert note.folder == FOLDER
    assert note.title == "A thought"
    assert "the body" in note.body


def test_a_capture_is_timestamped_so_two_notes_do_not_collide():
    first = build_note("Same", "one", now=datetime(2026, 8, 23, 9, 0, tzinfo=UTC))
    second = build_note("Same", "two", now=datetime(2026, 8, 23, 14, 30, tzinfo=UTC))

    assert first.slug != second.slug


def test_an_empty_capture_is_refused():
    with pytest.raises(CaptureRefused):
        build_note("title", "   ")


def test_an_oversized_capture_is_refused():
    with pytest.raises(CaptureRefused):
        build_note("title", "x" * (MAX_BODY + 1))


def test_a_traversing_title_cannot_leave_the_vault(tmp_path):
    vault = ObsidianVault(tmp_path / "vault")

    written = capture(vault, "../../../etc/passwd", "body")

    assert written.endswith(".md")
    assert vault.written[0].resolve().is_relative_to((tmp_path / "vault").resolve())
    assert not (tmp_path / "etc").exists()


def test_a_note_whose_folder_escapes_the_vault_is_refused(tmp_path):
    """The hardening this route made necessary.

    The filename was already safe — `Path(filename).stem` drops any directory
    part. The *folder* went into the path unchecked, which was theoretical
    while every note came from a constant in this repository and stopped being
    theoretical when an HTTP route started writing notes.
    """
    vault = ObsidianVault(tmp_path / "vault")
    escaping = VaultNote(slug="x", folder="../../elsewhere", title="x")

    with pytest.raises(ValueError, match="escapes the vault"):
        vault.write(escaping)

    assert not (tmp_path / "elsewhere").exists()


def test_an_ordinary_note_still_writes(tmp_path):
    vault = ObsidianVault(tmp_path / "vault")
    path = capture(vault, "Ordinary", "a body")

    assert (tmp_path / "vault" / FOLDER).is_dir()
    assert "a body" in (tmp_path / "vault" / FOLDER).glob("*.md").__next__().read_text(
        encoding="utf-8"
    )
    assert path.endswith(".md")


def test_capture_works_against_a_memory_vault():
    vault = MemoryVault()
    capture(vault, "In memory", "body")

    assert vault.written and vault.written[0].startswith(FOLDER + "/")


# --- The whole thing together --------------------------------------------


def test_a_dashboard_can_be_built_from_a_real_console_session(diagnostics, overlay):
    """End to end, with no server and no network."""
    session = build_session(settings())
    session.submit("Research Kestrel Systems")

    dashboard = build(
        state=overlay,
        conversation=session.conversation,
        telemetry=demo_telemetry(),
        diagnostics=diagnostics,
    )

    assert dashboard.turns
    assert any(member.tasks for member in dashboard.fleet)
    assert render_dashboard(dashboard)
