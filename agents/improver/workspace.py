"""Where patches are written and checks are run.

One `Protocol`, an in-memory implementation, and a real one that shells out to
git and the test runner.

**The demo and the tests use the in-memory workspace exclusively.** A demo of a
code-modifying agent that modified the repository it was demonstrating in would
be an unpleasant surprise, and "it only creates a branch" is not reassuring
enough to be worth relying on. The mock records what would have happened and
touches nothing.

`GitWorkspace` is the real thing, and it is the one piece of this repository
that can damage a working tree. It is written to be readable for that reason,
and it refuses to start from a dirty tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

#: How long any single command may run before it is killed. A test suite that
#: hangs must not hang the weekly job with it.
COMMAND_TIMEOUT_S = 600


class CommandResult(BaseModel):
    """The outcome of running one check."""

    command: str
    exit_code: int
    output: str = ""

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    @property
    def tail(self) -> str:
        """The last few lines, which is where a runner puts the summary."""
        return "\n".join(self.output.strip().splitlines()[-6:])


class Workspace(Protocol):
    """Everything the improver needs to do to a checkout."""

    def read(self, path: str) -> str: ...

    def write(self, path: str, text: str) -> None: ...

    def create_branch(self, name: str) -> None: ...

    def discard_changes(self) -> None: ...

    def run(self, command: str) -> CommandResult: ...


class MockWorkspace:
    """An in-memory checkout. Touches no filesystem and no git repository.

    Command results are scripted per patch: `results[branch][command]`. A
    command with no scripted result is treated as passing, so a test only has
    to script the failure it is about.
    """

    def __init__(
        self,
        files: dict[str, str] | None = None,
        results: dict[str, dict[str, CommandResult]] | None = None,
    ) -> None:
        self.files = dict(files or {})
        self._original = dict(self.files)
        self.results = results or {}

        self.branches: list[str] = []
        self.current_branch = "main"
        self.commands: list[str] = []
        self.discards = 0

    def read(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write(self, path: str, text: str) -> None:
        self.files[path] = text

    def create_branch(self, name: str) -> None:
        self.branches.append(name)
        self.current_branch = name

    def discard_changes(self) -> None:
        """Restore the tree to how it started, as `git checkout .` would."""
        self.files = dict(self._original)
        self.current_branch = "main"
        self.discards += 1

    def run(self, command: str) -> CommandResult:
        self.commands.append(command)
        scripted = self.results.get(self.current_branch, {}).get(command)
        return scripted or CommandResult(command=command, exit_code=0, output="ok")


class GitWorkspace:
    """A real checkout. This one can change your working tree.

    NOT COVERED BY TESTS, and deliberately so: a test that exercised it would
    have to create branches and run subprocesses in a real repository, which is
    exactly the behaviour nothing in CI should be doing.

    Two guards are worth pointing at. It refuses to start from a tree with
    uncommitted changes, because discarding on a failed patch would take
    somebody's work with it. And every branch it creates is named
    `improve/...`, so what it produced is obvious in `git branch`.
    """

    def __init__(self, root: Path | str = ".", *, base_branch: str = "main") -> None:
        self.root = Path(root)
        self.base_branch = base_branch

        status = self._git("status", "--porcelain")
        if status.output.strip():
            raise RuntimeError(
                "the working tree has uncommitted changes. The improver discards "
                "its own changes when a patch fails verification, which would "
                "take yours with it. Commit or stash first."
            )

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def create_branch(self, name: str) -> None:
        if not name.startswith("improve/"):
            raise ValueError(
                f"refusing to create {name!r}: the improver only creates branches "
                f"under improve/, so its work is obvious in git branch"
            )
        self._git("checkout", self.base_branch)
        self._git("checkout", "-b", name)

    def discard_changes(self) -> None:
        self._git("checkout", ".")
        self._git("checkout", self.base_branch)

    def run(self, command: str) -> CommandResult:  # pragma: no cover - subprocess
        completed = subprocess.run(  # noqa: S602 - commands are repository constants
            command,
            shell=True,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
        )
        return CommandResult(
            command=command,
            exit_code=completed.returncode,
            output=(completed.stdout + completed.stderr),
        )

    def _git(self, *args: str) -> CommandResult:  # pragma: no cover - subprocess
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
        )
        return CommandResult(
            command=f"git {' '.join(args)}",
            exit_code=completed.returncode,
            output=(completed.stdout + completed.stderr),
        )
