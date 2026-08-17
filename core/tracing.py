"""Run tracing.

Every run writes one JSON file containing each step, its tokens, its cost, and
its latency. The report agent reads these files, and so can you — an agent you
cannot inspect after the fact is an agent you cannot debug.

Traces embed prompts and tool output, so `traces/` is git-ignored.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.models import RunResult


class TraceWriter:
    """Writes one JSON file per run into a directory."""

    def __init__(self, directory: Path | str = "traces", *, enabled: bool = True) -> None:
        self.directory = Path(directory)
        self.enabled = enabled

    def write(self, result: RunResult) -> Path | None:
        """Persist a run. Returns the path written, or None when disabled."""
        if not self.enabled:
            return None

        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = result.started_at.strftime("%Y%m%dT%H%M%S")
        path = self.directory / f"{stamp}-{result.agent}-{result.run_id}.json"
        path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return path


def load_traces(directory: Path | str = "traces") -> list[RunResult]:
    """Read every trace in a directory, newest first.

    Malformed files are skipped rather than raising: a corrupt trace from an
    interrupted run should not stop you from reading the other twenty.
    """
    path = Path(directory)
    if not path.exists():
        return []

    results: list[RunResult] = []
    for file in sorted(path.glob("*.json"), reverse=True):
        try:
            results.append(RunResult.model_validate_json(file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError):
            continue
    return results
