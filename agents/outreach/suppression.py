"""The do-not-contact list.

The smallest component in this package and the one with the least room for
error. Everything else here can be wrong in a way that wastes an email; this
being wrong writes to somebody who explicitly asked not to be written to.

Two implementations, both real. The in-memory one is for tests. The file-backed
one appends a line per entry to a JSONL file, which is deliberately the dullest
storage possible: readable in an editor, greppable, survives a crash mid-write,
and mergeable by hand when two people maintain one.

Matching is on the address and on its domain. A firm that asks to be left alone
means the firm, not one mailbox at it — `info@` opting out suppresses
`m.reiter@` too, and it is the entry `@reiter-bedachungen.example` that says so.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class SuppressionEntry(BaseModel):
    """One address or domain that must never be written to again."""

    value: str = Field(description="An address, or a domain written as @domain.")
    reason: str = ""
    added_on: date | None = None

    @property
    def is_domain(self) -> bool:
        return self.value.startswith("@")

    def matches(self, address: str) -> bool:
        target = address.strip().lower()
        if self.is_domain:
            return target.endswith(self.value.lower())
        return target == self.value.strip().lower()


class SuppressionProvider(Protocol):
    """What outreach needs to know before writing to anyone."""

    def blocks(self, address: str) -> SuppressionEntry | None: ...

    def add(self, value: str, reason: str = "") -> SuppressionEntry: ...


class MemorySuppressionList:
    """An in-memory list, for tests and for a run nobody wants to persist."""

    def __init__(self, entries: list[SuppressionEntry | str] | None = None) -> None:
        self._entries: list[SuppressionEntry] = [
            entry if isinstance(entry, SuppressionEntry) else SuppressionEntry(value=entry)
            for entry in entries or []
        ]

    @property
    def entries(self) -> list[SuppressionEntry]:
        return list(self._entries)

    def blocks(self, address: str) -> SuppressionEntry | None:
        return next((entry for entry in self._entries if entry.matches(address)), None)

    def add(self, value: str, reason: str = "") -> SuppressionEntry:
        entry = SuppressionEntry(value=value.strip().lower(), reason=reason, added_on=date.today())
        self._entries.append(entry)
        return entry


class FileSuppressionList(MemorySuppressionList):
    """A JSONL file on disk, read once and appended to.

    A malformed line is skipped rather than fatal. The alternative — refusing to
    start because someone hand-edited the file badly — means the next run
    proceeds with *no* suppression list at all, which is the one failure this
    module exists to prevent.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        super().__init__(self._load())

    def _load(self) -> list[SuppressionEntry]:
        if not self.path.exists():
            return []

        entries: list[SuppressionEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entries.append(SuppressionEntry.model_validate(json.loads(stripped)))
            except (json.JSONDecodeError, ValueError):
                continue
        return entries

    def add(self, value: str, reason: str = "") -> SuppressionEntry:
        entry = super().add(value, reason)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
        return entry
