"""Synthetic telemetry, for the machine that has never run Claude Code.

`make demo` has to work on a laptop that was unboxed this morning, and a
dashboard whose every panel reads zero demonstrates nothing. So there are
fixtures — and one rule about them:

    fixtures are always labelled as fixtures.

`Telemetry.real` is False here and the header says so on screen. A heatmap that
silently shows invented data is worse than an empty one, because you would
believe it. Every number below is deterministic: a seeded generator, so two
runs produce the same picture and a screenshot stays true.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from telemetry.models import Activity, DayActivity, LiveSession, ModelShare, Telemetry

#: Fixed so the demo looks the same every time it is run or screenshotted.
SEED = 20260823

#: Deliberately invented project names. Nothing here is derived from a real
#: directory on anybody's machine.
PROJECTS = ["Sessions", "atlas-api", "field-notes"]


def _days(window: int, today: date, rng: random.Random) -> list[DayActivity]:
    """A month of plausible activity: busy weekdays, quiet weekends."""
    cells: list[DayActivity] = []
    for offset in range(window - 1, -1, -1):
        day = today - timedelta(days=offset)
        weekend = day.weekday() >= 5
        base = rng.randint(0, 2) if weekend else rng.randint(1, 6)
        # Two dead days, because a real month has them and a heatmap with no
        # gaps looks generated.
        if offset in (11, 12):
            base = 0
        messages = base * rng.randint(14, 60)
        cells.append(
            DayActivity(
                day=day,
                sessions=base,
                messages=messages,
                cost_usd=round(messages * rng.uniform(0.004, 0.012), 4),
            )
        )
    return cells


def demo_telemetry(*, window_days: int = 30, now: datetime | None = None) -> Telemetry:
    """A month of invented activity, honestly labelled."""
    now = now or datetime.now(UTC)
    rng = random.Random(SEED)
    today = now.astimezone().date()

    days = _days(window_days, today, rng)
    sessions = sum(cell.sessions for cell in days)
    messages = sum(cell.messages for cell in days)
    cost = round(sum(cell.cost_usd for cell in days), 4)

    # A working day: nothing overnight, a peak late morning, a second after
    # lunch. Uniform noise across 24 hours would not look like anyone's week.
    shape = [0, 0, 0, 0, 0, 1, 2, 5, 9, 14, 18, 16, 9, 12, 15, 13, 10, 7, 5, 4, 3, 2, 1, 0]
    scale = max(1, messages // max(1, sum(shape)))
    hourly = [count * scale + rng.randint(0, 3) for count in shape]

    split = [("opus", 62), ("sonnet", 31), ("haiku", 7)]
    models = [
        ModelShare(
            family=family,
            sessions=max(1, round(sessions * percent / 100)),
            percent=percent,
            cost_usd=round(cost * percent / 100, 4),
            tokens=round(messages * percent * 180),
        )
        for family, percent in split
    ]

    return Telemetry(
        real=False,
        source="fixtures — no Claude Code history found",
        scanned_at=now,
        window_days=window_days,
        sessions=sessions,
        messages=messages,
        tool_calls=round(messages * 0.8),
        tokens=sum(share.tokens for share in models),
        cost_usd=cost,
        days=days,
        hourly=hourly,
        models=models,
        projects=PROJECTS,
        live=demo_live(),
    )


def demo_live() -> list[LiveSession]:
    """Three sessions in the three states the panel can show.

    One working, one waiting on a person, one delegating — so the demo proves
    the states are distinguishable rather than showing three identical rows.
    """
    return [
        LiveSession(
            session_id="9f2c1a7b",
            project="Sessions",
            model="claude-opus-5",
            tool="Bash",
            activity=Activity.WORKING,
            age_seconds=4,
            recent_messages=38,
        ),
        LiveSession(
            session_id="41d8e0c3",
            project="atlas-api",
            model="claude-sonnet-5",
            subagent="Explore",
            activity=Activity.WORKING,
            age_seconds=21,
            recent_messages=12,
        ),
        LiveSession(
            session_id="6b03fd11",
            project="field-notes",
            model="claude-opus-5",
            activity=Activity.WAITING,
            age_seconds=143,
            recent_messages=7,
        ),
    ]
