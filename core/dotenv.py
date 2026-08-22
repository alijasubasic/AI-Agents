"""Reading a `.env` file.

`.env.example` has told people to copy it to `.env` since the first commit, and
until this module existed nothing read the result. That is a worse failure than
having no support at all: the instruction looked followed, the values looked
set, and every setting silently stayed at its default.

Written against the standard library rather than pulling in `python-dotenv`.
Parsing `KEY=value` lines is twenty lines and one clear rule about precedence,
and the alternative is a dependency in every install for that.

**The real environment always wins.** A value already in `os.environ` is left
alone, because CI sets variables deliberately and a stale `.env` on a developer
machine must never quietly override them.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PATH = ".env"


def parse(text: str) -> dict[str, str]:
    """Parse `.env` contents into a mapping.

    Deliberately small. Handles comments, blank lines, `export` prefixes, and
    surrounding quotes; does not handle multi-line values or variable
    interpolation, because nothing in this repository needs them and every
    feature here is one more thing that can behave differently from what a
    reader expects.
    """
    values: dict[str, str] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        # A quoted value keeps its inner whitespace; an unquoted one is taken
        # as written, which is what a Windows path with spaces needs.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        values[key] = value

    return values


def load(path: Path | str = DEFAULT_PATH, *, override: bool = False) -> dict[str, str]:
    """Load a `.env` into the environment. Returns what it set.

    Missing file is not an error: the whole repository runs on defaults, and
    demanding a `.env` would break the promise that a fresh clone works.
    """
    file = Path(path)
    if not file.exists():
        return {}

    applied: dict[str, str] = {}
    for key, value in parse(file.read_text(encoding="utf-8")).items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value

    return applied
