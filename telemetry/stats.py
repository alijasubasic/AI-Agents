"""Thirty days of history, aggregated once and then never again.

The expensive part of this package is reading whole transcripts. The saving
grace is that **a finished transcript never changes**, so the work is done once
per file for the life of the machine and the answer is kept on disk against the
file's modification time.

That is the whole cache design, and it is worth stating why it is not a
time-to-live. A TTL cache re-reads everything every five minutes whether or not
anything happened — which on a quiet afternoon is gigabytes of I/O to produce a
byte-identical answer, and on a busy one is a five-minute-stale dashboard. Keyed
on mtime, a refresh costs one `stat` per file plus a full read of only the files
that actually changed.

The cache lives in a git-ignored directory and holds counts, not content.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from telemetry.models import DayActivity, ModelShare, SessionSummary, Telemetry
from telemetry.parser import parse_whole
from telemetry.pricing import model_family
from telemetry.scanner import DEFAULT_ROOT, live_sessions, project_dirs, project_label, transcripts

#: Git-ignored. Counts only — see the module docstring.
CACHE_PATH = Path(".cache") / "telemetry.json"

#: Bumped whenever `SessionSummary` gains or changes a field.
#:
#: Without this, an entry written by older code validates cleanly — every new
#: field has a default — and is served forever, because the transcript's
#: modification time has not changed and so it is never re-read. The symptom is
#: a panel that is quietly, permanently wrong: `daily` was added, every cached
#: session came back with it empty, and the heatmap collapsed a week of work
#: onto one day. It cost twenty minutes to find. A version integer costs a line.
CACHE_VERSION = 2

WINDOW_DAYS = 30


def _load_cache(path: Path) -> dict[str, SessionSummary]:
    """Whatever survives from the last scan.

    A cache that fails to parse, or that was written by a different schema, is
    a cache that gets rebuilt rather than an error. There is nothing in it that
    cannot be recomputed from the transcripts.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != CACHE_VERSION:
        return {}

    kept: dict[str, SessionSummary] = {}
    for key, value in (raw.get("sessions") or {}).items():
        try:
            kept[key] = SessionSummary.model_validate(value)
        except ValidationError:
            continue
    return kept


def _save_cache(path: Path, summaries: dict[str, SessionSummary]) -> None:
    """Best effort. A read-only disk should not take the dashboard down."""
    payload = {
        "version": CACHE_VERSION,
        "written_at": datetime.now(UTC).isoformat(),
        "sessions": {key: value.model_dump(mode="json") for key, value in summaries.items()},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def summarise(
    root: Path | None = None,
    *,
    cache_path: Path | None = CACHE_PATH,
    window_days: int = WINDOW_DAYS,
    now: datetime | None = None,
) -> list[SessionSummary]:
    """Every transcript in the window, read from cache where possible."""
    root = root or DEFAULT_ROOT
    now = now or datetime.now(UTC)
    cutoff = (now - timedelta(days=window_days)).timestamp()

    cached = _load_cache(cache_path) if cache_path else {}
    fresh: dict[str, SessionSummary] = {}
    results: list[SessionSummary] = []

    for directory in project_dirs(root):
        label = project_label(directory.name)
        for path in transcripts(directory, include_subagents=False):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                # Newest-first, so everything left in this project is older.
                break

            key = str(path)
            hit = cached.get(key)
            summary = hit if hit and hit.mtime == mtime else parse_whole(path, label)
            if summary is None:
                continue
            # A cache hit predates any rename of the project directory.
            summary.project = label
            fresh[key] = summary
            results.append(summary)

    if cache_path:
        _save_cache(cache_path, fresh)
    return results


def aggregate(
    summaries: list[SessionSummary],
    *,
    window_days: int = WINDOW_DAYS,
    today: date | None = None,
) -> Telemetry:
    """Roll a list of sessions up into what the dashboard renders.

    The day series is dense — every day in the window gets a cell, including
    the empty ones. A heatmap that omits quiet days is a heatmap that lies
    about how quiet they were.
    """
    today = today or datetime.now().astimezone().date()
    start = today - timedelta(days=window_days - 1)

    by_day: dict[date, DayActivity] = {
        start + timedelta(days=offset): DayActivity(day=start + timedelta(days=offset))
        for offset in range(window_days)
    }
    hourly = [0] * 24
    per_family: dict[str, dict[str, float]] = defaultdict(
        lambda: {"sessions": 0.0, "cost": 0.0, "tokens": 0.0}
    )

    total = Telemetry(window_days=window_days, sessions=len(summaries))

    for summary in summaries:
        total.messages += summary.messages
        total.tool_calls += summary.tool_calls
        total.tokens += summary.total_tokens
        total.cost_usd += summary.cost_usd

        family = per_family[model_family(summary.model)]
        family["sessions"] += 1
        family["cost"] += summary.cost_usd
        family["tokens"] += summary.total_tokens

        for hour, count in summary.hours.items():
            if 0 <= hour < 24:
                hourly[hour] += count

        # A session counts once, on the day it began — that is what a session
        # count means. Its *messages* are spread across the days they actually
        # happened on, so a run spanning three days lights three cells.
        if summary.day in by_day:
            by_day[summary.day].sessions += 1

        spread = summary.daily or ({summary.day: summary.messages} if summary.day else {})
        total_messages = sum(spread.values()) or 1
        for when, count in spread.items():
            if when not in by_day:
                continue
            by_day[when].messages += count
            # Cost follows the messages, for want of anything better: the
            # transcript prices a request, not a day, and splitting by volume
            # is the honest approximation rather than dumping it all on day one.
            by_day[when].cost_usd += summary.cost_usd * count / total_messages

    total.hourly = hourly
    total.days = [by_day[key] for key in sorted(by_day)]
    total.projects = sorted({summary.project for summary in summaries})
    total.models = sorted(
        (
            ModelShare(
                family=name,
                sessions=int(values["sessions"]),
                percent=round(values["sessions"] / len(summaries) * 100) if summaries else 0,
                cost_usd=values["cost"],
                tokens=int(values["tokens"]),
            )
            for name, values in per_family.items()
        ),
        key=lambda share: (-share.sessions, share.family),
    )
    return total


def collect(
    root: Path | None = None,
    *,
    cache_path: Path | None = CACHE_PATH,
    window_days: int = WINDOW_DAYS,
    now: datetime | None = None,
) -> Telemetry:
    """Everything the dashboard knows, from a real scan.

    Returns an empty-but-real `Telemetry` when there is nothing to find, rather
    than falling back to fixtures here. Substituting synthetic data is a
    decision the caller makes visibly — see `telemetry.fixtures.demo_telemetry`
    and the `real` flag it sets.
    """
    root = root or DEFAULT_ROOT
    now = now or datetime.now(UTC)

    summaries = summarise(root, cache_path=cache_path, window_days=window_days, now=now)
    total = aggregate(summaries, window_days=window_days, today=now.astimezone().date())
    total.real = True
    total.source = str(root)
    total.scanned_at = now
    total.live = live_sessions(root, now=now)
    return total
