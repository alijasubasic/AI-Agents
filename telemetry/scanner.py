"""Finding the transcripts, and deciding which ones are alive.

Claude Code keeps one directory per project under `~/.claude/projects`, named
after the working directory with the separators flattened:

    ~/.claude/projects/D--Claude-Sessions/<session-uuid>.jsonl
                       └── project dir      └── one transcript

Subagent transcripts live one level deeper, under `<session-uuid>/subagents/`.

Two things this module refuses to do, both borrowed decisions reversed:

* **It does not shell out to `pgrep`.** The source dashboard runs
  `pgrep -fa claude` to decide whether Claude Code is running, which is a
  process listing on every refresh, is Unix-only, and answers the wrong
  question anyway — a *running binary* says nothing about whether *this*
  transcript is active. File modification time answers the actual question and
  costs a `stat`.
* **It does not follow the path outside the scan root.** A directory entry is
  resolved and checked against the root before it is read, so a symlink
  planted in `~/.claude/projects` cannot make this walk somebody's documents.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from telemetry.models import Activity, LiveSession
from telemetry.parser import parse_tail

#: Where Claude Code keeps transcripts, unless told otherwise.
DEFAULT_ROOT = Path.home() / ".claude" / "projects"

#: A transcript older than this is not shown as live, however interesting.
LIVE_WINDOW_SECONDS = 900

#: Enough to fill the panel. Sorted by recency first, so the cut is the boring
#: end of the list.
MAX_LIVE = 8


def project_label(directory: str) -> str:
    """A short name for a flattened project directory.

    `D--Claude-Sessions` becomes `Sessions`. The full path is on this machine
    already, so shortening loses nothing — and the short form is the one that
    fits in a panel and does not put somebody's directory layout on screen
    during a screen share.
    """
    parts = [part for part in directory.split("-") if part]
    return parts[-1] if parts else directory


def _within(candidate: Path, root: Path) -> bool:
    """True if `candidate` really lives under `root` once symlinks resolve."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def project_dirs(root: Path | None = None) -> list[Path]:
    """Every project directory under the scan root, newest activity first."""
    root = root or DEFAULT_ROOT
    try:
        entries = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return []
    found = [entry for entry in entries if _within(entry, root)]
    return sorted(found, key=lambda path: _mtime(path), reverse=True)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def transcripts(directory: Path, *, include_subagents: bool = True) -> Iterator[Path]:
    """Every transcript belonging to one project, newest first.

    Subagent transcripts are included because a delegated run is the part of a
    fleet worth watching — the parent session just says "Agent" and waits.
    """
    try:
        files = [path for path in directory.glob("*.jsonl") if path.is_file()]
    except OSError:
        return

    if include_subagents:
        with contextlib.suppress(OSError):
            files += [
                path
                for path in directory.glob("*/subagents/agent-*.jsonl")
                if path.is_file() and _within(path, directory)
            ]

    yield from sorted(files, key=_mtime, reverse=True)


def subagent_type(path: Path) -> str:
    """What kind of subagent a delegated transcript belongs to.

    Claude Code writes an `agent-<id>.meta.json` beside each subagent
    transcript. Reading it is the only way to name the agent from the child
    file alone — the parent session holds the `Agent` tool call that named it,
    and correlating the two would mean reading the parent on every refresh.

    Falls back to a generic label rather than to the parent session's id: an id
    where a name belongs reads like a name, and someone will believe it.
    """
    meta = path.parent / f"{path.stem}.meta.json"
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "subagent"
    kind = payload.get("agentType") if isinstance(payload, dict) else None
    return kind if isinstance(kind, str) and kind else "subagent"


def live_sessions(
    root: Path | None = None,
    *,
    window_seconds: int = LIVE_WINDOW_SECONDS,
    limit: int = MAX_LIVE,
    now: datetime | None = None,
) -> list[LiveSession]:
    """The transcripts that changed recently enough to be worth a row.

    Filtered on modification time *before* anything is read, so a machine with
    years of history costs one `stat` per file rather than one seek per file.
    """
    now = now or datetime.now(UTC)
    cutoff = now.timestamp() - window_seconds
    found: list[LiveSession] = []

    for directory in project_dirs(root):
        label = project_label(directory.name)
        for path in transcripts(directory):
            if _mtime(path) < cutoff:
                # Files are newest-first, so the rest of this project is older.
                break
            session = parse_tail(path, label, now=now)
            if session and session.activity is not Activity.IDLE:
                if path.name.startswith("agent-"):
                    session.subagent = session.subagent or subagent_type(path)
                found.append(session)

    found.sort(key=lambda session: session.age_seconds)
    return found[:limit]
