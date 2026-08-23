"""Checks that the repository's own configuration matches its contents.

These are cheap and they catch the class of mistake that is invisible in
review: a change that is correct everywhere except in the file that decides
whether anyone runs it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Directories that are not Python packages of ours.
_IGNORED = {".venv", "venv", "build", "dist", "traces", "briefs", "vault", ".cache", "docs"}


def config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def packages_with_tests() -> set[str]:
    """Top-level directories that contain tests somewhere beneath them."""
    found = set()
    for entry in ROOT.iterdir():
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in _IGNORED:
            continue
        if any(entry.rglob("test_*.py")):
            found.add(entry.name)
    return found


def test_every_package_with_tests_is_a_pytest_root():
    """The mistake this exists for.

    `telemetry` and `jarvis` were added with a hundred tests between them.
    `pytest telemetry` ran them and passed; plain `pytest` — which is what CI
    runs — never saw them, because `testpaths` had not been extended. The tests
    existed, passed locally, and protected nothing.
    """
    declared = set(config()["tool"]["pytest"]["ini_options"]["testpaths"])
    missing = packages_with_tests() - declared

    assert missing == set(), f"packages with tests that CI will not run: {sorted(missing)}"


def test_no_pytest_root_is_a_directory_that_vanished():
    declared = config()["tool"]["pytest"]["ini_options"]["testpaths"]
    assert [name for name in declared if not (ROOT / name).is_dir()] == []


def test_the_makefile_demos_every_package_that_has_one():
    """`make demo` is the first thing anyone runs. It should be complete.

    A demo module nobody invokes is a demo that rots — and the whole promise of
    this repository is that a clone runs.
    """
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    demo_block = makefile.split("demo:", 1)[1].split("\n\n", 1)[0]

    modules = set()
    for entry in ROOT.iterdir():
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in _IGNORED:
            continue
        if (entry / "demo.py").exists():
            modules.add(f"{entry.name}.demo")
        modules |= {
            f"{entry.name}.{child.name}.demo"
            for child in entry.iterdir()
            if child.is_dir() and (child / "demo.py").exists()
        }

    missing = {module for module in modules if module not in demo_block}
    assert missing == set(), f"demo modules `make demo` does not run: {sorted(missing)}"
