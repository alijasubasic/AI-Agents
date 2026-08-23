"""Reading this machine's own Claude Code history.

Every other agent in this repository runs on fixtures, and says so. This
package is the exception: it is the one component whose data is real, because
the data is already sitting on the disk and needs no account, no key and no
network to read.

    from telemetry import load
    telemetry = load()          # real if there is history, fixtures if not

`load` never pretends. `Telemetry.real` says which of the two you got, and the
dashboard prints it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from telemetry.fixtures import demo_telemetry
from telemetry.models import (
    Activity,
    DayActivity,
    LiveSession,
    ModelShare,
    SessionSummary,
    Telemetry,
)
from telemetry.scanner import DEFAULT_ROOT
from telemetry.stats import CACHE_PATH, WINDOW_DAYS, aggregate, collect, summarise

__all__ = [
    "CACHE_PATH",
    "DEFAULT_ROOT",
    "WINDOW_DAYS",
    "Activity",
    "DayActivity",
    "LiveSession",
    "ModelShare",
    "SessionSummary",
    "Telemetry",
    "aggregate",
    "collect",
    "demo_telemetry",
    "load",
    "summarise",
]


def load(
    root: Path | None = None,
    *,
    allow_fixtures: bool = True,
    window_days: int = WINDOW_DAYS,
    cache_path: Path | None = CACHE_PATH,
    now: datetime | None = None,
) -> Telemetry:
    """Real telemetry where there is any, fixtures where there is not.

    The fallback is on session count rather than on whether the directory
    exists: an empty `~/.claude/projects` is the common case on a machine where
    Claude Code was installed and never used, and it should demo like a fresh
    machine rather than like a broken one.

    Pass `allow_fixtures=False` to get the honest empty result instead — that is
    what the tests use, and what anyone measuring real usage should use.
    """
    now = now or datetime.now(UTC)
    real = collect(root, cache_path=cache_path, window_days=window_days, now=now)
    if real.sessions or real.live or not allow_fixtures:
        return real
    return demo_telemetry(window_days=window_days, now=now)
