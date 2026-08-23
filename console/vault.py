"""Recording everything into an Obsidian vault.

An Obsidian vault is a folder of Markdown files, which makes this the one
integration in the repository that can be built completely and tested for
real — no account, no API, no skeleton.

The idea worth taking from it: **wikilinks turn an audit log into something a
person can actually navigate.** Every decision note links to the agent that
made it, to each codex article that fired on it, and to the day's brief. Open
`A2 Honesty` in Obsidian and its backlinks pane lists every decision that
article has ever blocked. Nobody had to build that view; it falls out of
writing the links.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol

from console.models import VaultNote

#: Characters Windows forbids in filenames, plus the ones Obsidian treats as
#: link syntax. A note whose name contains any of them either fails to write or
#: silently breaks every link pointing at it.
_UNSAFE = re.compile(r'[<>:"/\|?*#^\[\]]+')
_WHITESPACE = re.compile(r"\s+")


def safe_slug(text: str, *, max_length: int = 80) -> str:
    """Turn arbitrary text into a filename that survives Windows and Obsidian."""
    cleaned = _UNSAFE.sub("", text)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip(" .")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or "untitled"


def _yaml_value(value: object) -> str:
    """Render one frontmatter value.

    Deliberately minimal rather than pulling in a YAML library: the values here
    are strings, numbers, booleans and flat lists, and quoting those correctly
    is a dozen lines.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(f'"{str(item)}"' for item in value) + "]"

    text = str(value)
    if text == "" or any(char in text for char in ':#"\n{}[]'):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def render_note(note: VaultNote) -> str:
    """Render a note as Markdown with YAML frontmatter."""
    lines = ["---"]
    lines += [f"{key}: {_yaml_value(value)}" for key, value in note.frontmatter.items()]
    lines += ["---", "", f"# {note.title}", ""]

    if note.body:
        lines += [note.body, ""]

    if note.links:
        lines += ["## Linked", ""]
        lines += [f"- [[{link}]]" for link in note.links]
        lines.append("")

    return "\n".join(lines)


class VaultWriter(Protocol):
    """Somewhere notes can be written."""

    def write(self, note: VaultNote) -> str: ...


class ObsidianVault:
    """Writes notes into a real Obsidian vault directory.

    Slugs are stable, so re-running a day rewrites its notes rather than
    accumulating `note 1.md`, `note 2.md`. That matters more than it sounds:
    an audit trail that duplicates on every run is one nobody trusts, and one
    that appends silently is one nobody can diff.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        #: Every path written this session, for the demo and the tests.
        self.written: list[Path] = []

    def _target(self, note: VaultNote) -> Path:
        """Where a note lands, having proved it lands inside the vault.

        The filename was already safe — `Path(filename).stem` drops any
        directory part before `safe_slug` ever sees it. **The folder was not.**
        `note.folder` went into the path unchecked, so a note asking for
        `../../..` wrote wherever it liked.

        That was theoretical while every note was built in this repository from
        a fixed folder constant. It stopped being theoretical when the dashboard
        gained an HTTP route that writes notes, so the containment is asserted
        here rather than trusted at each call site — one check on the way to
        disk covers every writer, including the ones nobody has written yet.
        """
        folder, filename = note.path_parts
        candidate = self.root / folder / f"{safe_slug(Path(filename).stem)}.md"

        root = self.root.resolve()
        # `strict=False`: the note does not exist yet, and neither may its
        # folder. Resolution still normalises away every `..` in the path.
        if not candidate.resolve(strict=False).is_relative_to(root):
            raise ValueError(f"note folder escapes the vault: {folder!r}")
        return candidate

    def write(self, note: VaultNote) -> str:
        path = self._target(note)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_note(note), encoding="utf-8")
        self.written.append(path)
        return str(path)

    def read(self, note: VaultNote) -> str:
        """Read a note back. Used by tests and by anything checking for drift."""
        return self._target(note).read_text(encoding="utf-8")


class MemoryVault:
    """An in-memory vault. Nothing touches the filesystem."""

    def __init__(self) -> None:
        self.notes: dict[str, str] = {}

    def write(self, note: VaultNote) -> str:
        folder, filename = note.path_parts
        key = f"{folder}/{safe_slug(Path(filename).stem)}.md"
        self.notes[key] = render_note(note)
        return key

    @property
    def written(self) -> list[str]:
        return list(self.notes)


def build_vault(path: Path | str | None = None) -> VaultWriter:
    """Return a vault writer for `OBSIDIAN_VAULT_PATH`, or a local default.

    The default is a `vault/` folder inside the repository, which is
    git-ignored. Pointing this at a real vault is one environment variable, and
    keeping that opt-in means a clone can never write into somebody's notes by
    accident.
    """
    root = path or os.environ.get("OBSIDIAN_VAULT_PATH") or "vault"
    return ObsidianVault(root)
