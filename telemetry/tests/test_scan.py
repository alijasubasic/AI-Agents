"""Tests for discovery, aggregation and the cache.

Everything here runs against a fabricated `projects` tree in `tmp_path`.
Nothing reads the real `~/.claude` — a test whose result depends on how much
work the author did yesterday is a test that fails on somebody else's machine.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from telemetry import load
from telemetry.fixtures import demo_telemetry
from telemetry.models import SessionSummary
from telemetry.scanner import live_sessions, project_dirs, project_label, transcripts
from telemetry.stats import CACHE_VERSION, aggregate, collect, summarise

USAGE = {"input_tokens": 10, "output_tokens": 1_000_000}


def session_file(root, project: str, name: str, *, records=None, age: float = 5.0):
    directory = root / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jsonl"
    records = records if records is not None else [_assistant("m1")]
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def _assistant(message_id: str, *, stamp: str | None = None, usage=None, stop="tool_use"):
    return {
        "type": "assistant",
        "timestamp": stamp or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "message": {
            "id": message_id,
            "model": "claude-opus-5",
            "stop_reason": stop,
            "content": [{"type": "tool_use", "name": "Bash"}],
            "usage": usage or USAGE,
        },
    }


@pytest.fixture
def root(tmp_path):
    return tmp_path / "projects"


# --- Discovery -----------------------------------------------------------


def test_project_labels_are_short_and_do_not_leak_a_path():
    assert project_label("D--Claude-Sessions") == "Sessions"
    assert project_label("-Users-someone-work-atlas-api") == "api"
    assert project_label("plain") == "plain"


def test_projects_are_found_newest_first(root):
    session_file(root, "old", "a", age=9000)
    session_file(root, "new", "b", age=5)

    assert [path.name for path in project_dirs(root)] == ["new", "old"]


def test_a_missing_root_is_empty_not_an_error(tmp_path):
    assert project_dirs(tmp_path / "nothing-here") == []
    assert live_sessions(tmp_path / "nothing-here") == []


def test_subagent_transcripts_are_included(root):
    session_file(root, "proj", "main")
    subagents = root / "proj" / "main" / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-abc.jsonl").write_text(json.dumps(_assistant("m")), encoding="utf-8")

    found = [path.name for path in transcripts(root / "proj")]

    assert "agent-abc.jsonl" in found
    assert "main.jsonl" in found


def test_a_subagent_is_named_from_its_meta_file(root):
    session_file(root, "proj", "main", age=9000)
    subagents = root / "proj" / "main" / "subagents"
    subagents.mkdir(parents=True)
    child = subagents / "agent-abc.jsonl"
    child.write_text(json.dumps(_assistant("m")), encoding="utf-8")
    (subagents / "agent-abc.meta.json").write_text('{"agentType": "Explore"}', encoding="utf-8")
    when = time.time() - 3
    os.utime(child, (when, when))

    found = live_sessions(root)

    assert [s.subagent for s in found] == ["Explore"]


def test_a_subagent_without_a_meta_file_gets_a_generic_label(root):
    subagents = root / "proj" / "main" / "subagents"
    subagents.mkdir(parents=True)
    child = subagents / "agent-abc.jsonl"
    child.write_text(json.dumps(_assistant("m")), encoding="utf-8")
    when = time.time() - 3
    os.utime(child, (when, when))

    found = live_sessions(root)

    # Not the parent session's id: an id in a name slot reads like a name.
    assert [s.subagent for s in found] == ["subagent"]


# --- Liveness ------------------------------------------------------------


def test_only_recent_transcripts_are_live(root):
    session_file(root, "proj", "fresh", age=4)
    session_file(root, "proj", "stale", age=100_000)

    found = live_sessions(root)

    assert [session.session_id for session in found] == ["fresh"]


def test_live_sessions_are_ordered_by_recency(root):
    session_file(root, "a", "slower", age=60)
    session_file(root, "b", "faster", age=2)

    assert [s.session_id for s in live_sessions(root)] == ["faster", "slower"]


def test_the_live_list_is_capped(root):
    for index in range(12):
        session_file(root, f"p{index}", f"s{index}", age=index + 1)

    assert len(live_sessions(root, limit=4)) == 4


# --- Aggregation ---------------------------------------------------------


def test_the_day_series_is_dense(root):
    """Every day in the window gets a cell, including the empty ones.

    A heatmap that omits quiet days is a heatmap that lies about how quiet
    they were.
    """
    today = datetime(2026, 8, 23).date()
    summaries = [
        SessionSummary(
            session_id="a",
            project="p",
            started_at=datetime(2026, 8, 20, 10, tzinfo=UTC).astimezone(),
            messages=5,
        )
    ]

    total = aggregate(summaries, window_days=30, today=today)

    assert len(total.days) == 30
    assert total.days[-1].day == today
    assert sum(1 for day in total.days if day.messages) == 1


def test_activity_outside_the_window_is_not_counted_into_a_day(root):
    today = datetime(2026, 8, 23).date()
    summaries = [
        SessionSummary(
            session_id="ancient",
            project="p",
            started_at=datetime(2020, 1, 1, tzinfo=UTC).astimezone(),
            messages=99,
        )
    ]

    total = aggregate(summaries, window_days=30, today=today)

    # It still counts towards the totals it was handed, but it lands in no cell.
    assert total.sessions == 1
    assert sum(day.messages for day in total.days) == 0


def test_model_shares_add_up_and_sort_by_use():
    summaries = [
        SessionSummary(session_id=str(n), project="p", model="claude-opus-5") for n in range(3)
    ]
    summaries.append(SessionSummary(session_id="x", project="p", model="claude-haiku-4-5"))

    total = aggregate(summaries)

    assert [share.family for share in total.models] == ["opus", "haiku"]
    assert total.favourite is not None
    assert total.favourite.percent == 75


def test_the_busiest_hour_is_none_when_nothing_happened():
    assert aggregate([]).busiest_hour is None


def test_the_busiest_hour_is_the_fullest_bucket():
    summary = SessionSummary(session_id="a", project="p", hours={9: 3, 21: 40, 22: 12})
    assert aggregate([summary]).busiest_hour == 21


# --- The cache -----------------------------------------------------------


def test_the_cache_is_keyed_on_modification_time_not_a_clock(root, tmp_path):
    """The reason this is not a TTL.

    An unchanged transcript is never re-read, however long ago it was scanned.
    A five-minute TTL would re-read the whole history on a quiet afternoon to
    produce a byte-identical answer.
    """
    cache = tmp_path / "cache.json"
    session_file(root, "proj", "a")

    first = summarise(root, cache_path=cache)
    assert cache.exists()

    # Poison the cache. A second scan that returns the poisoned value proves
    # the file was not re-read.
    payload = json.loads(cache.read_text(encoding="utf-8"))
    key = next(iter(payload["sessions"]))
    payload["sessions"][key]["messages"] = 9999
    cache.write_text(json.dumps(payload), encoding="utf-8")

    second = summarise(root, cache_path=cache)

    assert first[0].messages != 9999
    assert second[0].messages == 9999


def test_a_changed_transcript_is_re_read(root, tmp_path):
    cache = tmp_path / "cache.json"
    path = session_file(root, "proj", "a")
    summarise(root, cache_path=cache)

    path.write_text("\n".join(json.dumps(_assistant(f"m{n}")) for n in range(4)), encoding="utf-8")

    assert summarise(root, cache_path=cache)[0].messages == 4


def test_a_corrupt_cache_is_rebuilt_not_fatal(root, tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("this is not json", encoding="utf-8")
    session_file(root, "proj", "a")

    assert summarise(root, cache_path=cache)[0].messages == 1


def test_a_cache_hit_picks_up_a_renamed_project(root, tmp_path):
    cache = tmp_path / "cache.json"
    session_file(root, "before", "a")
    summarise(root, cache_path=cache)

    (root / "before").rename(root / "after")

    assert summarise(root, cache_path=cache)[0].project == "after"


def test_transcripts_outside_the_window_are_not_read(root, tmp_path):
    session_file(root, "proj", "recent", age=60)
    session_file(root, "proj", "ancient", age=60 * 60 * 24 * 400)

    found = summarise(root, cache_path=None, window_days=30)

    assert [summary.session_id for summary in found] == ["recent"]


# --- load() --------------------------------------------------------------


def test_load_reports_real_data_as_real(root, tmp_path):
    session_file(root, "proj", "a")

    telemetry = load(root, cache_path=None)

    assert telemetry.real is True
    assert telemetry.sessions == 1


def test_load_falls_back_to_fixtures_and_says_so(tmp_path):
    telemetry = load(tmp_path / "empty", cache_path=None)

    assert telemetry.real is False
    assert "fixtures" in telemetry.source
    assert telemetry.sessions > 0


def test_load_can_refuse_the_fixtures(tmp_path):
    telemetry = load(tmp_path / "empty", cache_path=None, allow_fixtures=False)

    assert telemetry.real is True
    assert telemetry.sessions == 0


def test_collect_never_invents_data(tmp_path):
    telemetry = collect(tmp_path / "empty", cache_path=None)

    assert telemetry.real is True
    assert (telemetry.sessions, telemetry.cost_usd, telemetry.live) == (0, 0.0, [])


# --- Fixtures ------------------------------------------------------------


def test_the_fixtures_are_labelled_as_fixtures():
    telemetry = demo_telemetry()
    assert telemetry.real is False
    assert "fixtures" in telemetry.source


def test_the_fixtures_are_deterministic():
    """A screenshot of the demo has to stay true."""
    now = datetime(2026, 8, 23, 12, tzinfo=UTC)
    assert demo_telemetry(now=now).model_dump() == demo_telemetry(now=now).model_dump()


def test_the_fixtures_cover_the_whole_window_and_have_quiet_days():
    telemetry = demo_telemetry(window_days=30)

    assert len(telemetry.days) == 30
    assert any(day.sessions == 0 for day in telemetry.days), "a real month has dead days"
    assert sum(telemetry.hourly[0:5]) < sum(telemetry.hourly[9:14]), "nobody works at 3am"


def test_the_fixture_days_end_today():
    now = datetime(2026, 8, 23, 12, tzinfo=UTC)
    telemetry = demo_telemetry(now=now)

    assert telemetry.days[-1].day == now.astimezone().date()
    assert telemetry.days[0].day == now.astimezone().date() - timedelta(days=29)


def test_a_session_spanning_days_lights_every_day_it_touched():
    """The fix for an empty cell on a day you were visibly working.

    Attributing a whole session to `started_at` — which is what the source
    dashboard does — leaves today blank whenever a long run began yesterday.
    """
    today = datetime(2026, 8, 23).date()
    summary = SessionSummary(
        session_id="long",
        project="p",
        started_at=datetime(2026, 8, 21, 9, tzinfo=UTC).astimezone(),
        messages=300,
        cost_usd=30.0,
        daily={today - timedelta(days=2): 100, today - timedelta(days=1): 50, today: 150},
    )

    total = aggregate([summary], window_days=30, today=today)
    lit = {cell.day: cell.messages for cell in total.days if cell.messages}

    assert lit == {
        today - timedelta(days=2): 100,
        today - timedelta(days=1): 50,
        today: 150,
    }
    # The session itself is still counted once, on the day it began.
    assert sum(cell.sessions for cell in total.days) == 1
    # Cost follows the messages rather than landing entirely on day one.
    assert sum(cell.cost_usd for cell in total.days) == pytest.approx(30.0)
    assert next(c.cost_usd for c in total.days if c.day == today) == pytest.approx(15.0)


def test_a_session_without_a_daily_breakdown_falls_back_to_its_start_day():
    # Cache entries written before `daily` existed, and any transcript with no
    # usable timestamps.
    today = datetime(2026, 8, 23).date()
    summary = SessionSummary(
        session_id="old",
        project="p",
        started_at=datetime(2026, 8, 22, 9, tzinfo=UTC).astimezone(),
        messages=40,
    )

    total = aggregate([summary], window_days=30, today=today)

    assert next(c.messages for c in total.days if c.day == today - timedelta(days=1)) == 40


def test_a_cache_from_an_older_schema_is_discarded(root, tmp_path):
    """The failure a version integer exists to prevent.

    An entry written by older code validates cleanly — every new field has a
    default — and is then served forever, because the transcript's modification
    time has not changed and so it is never re-read. The result is a panel that
    is quietly and permanently wrong.
    """
    cache = tmp_path / "cache.json"
    path = session_file(root, "proj", "a")

    summarise(root, cache_path=cache)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    key = str(path)
    # An entry as an older version of the code would have written it.
    payload["version"] = 1
    payload["sessions"][key].pop("daily", None)
    payload["sessions"][key]["messages"] = 9999
    cache.write_text(json.dumps(payload), encoding="utf-8")

    again = summarise(root, cache_path=cache)

    assert again[0].messages == 1, "the stale entry was re-read, not trusted"
    assert json.loads(cache.read_text(encoding="utf-8"))["version"] == CACHE_VERSION
