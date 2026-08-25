"""Building an index of the codebase and choosing what to review.

Deterministic: the same tree always produces the same index and the same
ranking. A reviewer crew is the expensive part of a run, so which files it
looks at should be a decision somebody can inspect and disagree with, not the
output of a model's taste.

The ranking is deliberately simple and stated in the entry itself
(`priority_reasons`), so a run that spent its budget on the wrong file can be
argued with.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agents.code_reviewer.models import FileEntry
from agents.code_reviewer.safety import is_protected, is_self, normalise

#: Directories the scanner reads. Everything else is out of scope by
#: construction rather than by rule.
SOURCE_ROOTS: tuple[str, ...] = ("core", "agents", "console")

#: A file this long is doing several jobs and is worth a look for that reason
#: alone.
LONG_FILE_LINES = 300


def _parse(path: Path) -> tuple[list[str], list[str]]:
    """Top-level function and class names, and imported module names.

    Parsed rather than pattern-matched, because a regex over Python finds
    `def` inside a docstring and misses one after a decorator.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return [], []

    names: list[str] = []
    imports: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    return names, imports


def _test_path_for(path: Path, root: Path) -> Path | None:
    """Where a file's tests would live, if it has any.

    Two conventions in this repository: agents keep tests beside themselves in
    `<package>/tests/test_<name>.py`, and `core/` uses a top-level `tests/`.
    """
    candidates = [
        path.parent / "tests" / f"test_{path.stem}.py",
        root / "tests" / f"test_{path.stem}.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def scan(root: Path | str = ".") -> list[FileEntry]:
    """Index every source file, ranked by how much attention it deserves."""
    root = Path(root)
    entries: list[FileEntry] = []

    for source_root in SOURCE_ROOTS:
        base = root / source_root
        if not base.exists():
            continue

        for path in sorted(base.rglob("*.py")):
            relative = normalise(str(path.relative_to(root)))
            if "__pycache__" in relative:
                continue

            functions, imports = _parse(path)
            test_path = _test_path_for(path, root)
            entry = FileEntry(
                path=relative,
                lines=len(path.read_text(encoding="utf-8").splitlines()),
                functions=functions,
                imports=sorted(set(imports)),
                has_tests=test_path is not None,
                test_path=normalise(str(test_path.relative_to(root))) if test_path else None,
                is_self=is_self(relative),
                protected=is_protected(relative),
            )
            entry.priority, entry.priority_reasons = _rank(entry)
            entries.append(entry)

    return sorted(entries, key=lambda entry: (-entry.priority, entry.path))


def _rank(entry: FileEntry) -> tuple[float, list[str]]:
    """Score a file for review, and say why.

    Untested code first: a defect there has nothing standing between it and
    production. But "untested" is only interesting in proportion to how much
    logic is at stake, which is what the first version of this got wrong — a
    flat bonus for having no test module put every `__init__.py` and every
    `models.py` at the top of the list, and the crew would have spent its
    budget reviewing re-exports.
    """
    if entry.protected or entry.is_self:
        return 0.0, ["excluded: protected or part of the code reviewer"]

    definitions = len(entry.functions)

    # A package __init__ that only re-exports has nothing to review. One that
    # defines something is an ordinary module and is ranked as one.
    if entry.path.endswith("__init__.py") and definitions == 0:
        return 0.0, ["re-export module, nothing to review"]

    score = 0.0
    reasons: list[str] = []

    if not entry.has_tests and definitions:
        # Scaled by how much is at stake, and capped: past a point, "large and
        # untested" is one fact rather than an accumulating one.
        bonus = min(definitions, 8) * 0.4
        score += bonus
        reasons.append(f"no test file, {definitions} definitions")

    if entry.lines > LONG_FILE_LINES:
        score += 1.5
        reasons.append(f"{entry.lines} lines")

    if definitions > 12:
        score += 1.0
        reasons.append(f"{definitions} top-level definitions")

    # Entry points are the code least likely to be exercised by a unit test and
    # most likely to be seen by a person.
    if entry.path.endswith(("demo.py", "__main__.py", "cli.py")):
        score += 0.25
        reasons.append("entry point")

    if not reasons:
        reasons.append("no signals")

    return score, reasons


def candidates(entries: list[FileEntry], *, limit: int = 3) -> list[FileEntry]:
    """The files worth spending a reviewer crew on.

    Files scoring zero are never returned, however short the list gets. An
    code reviewer that reviews protected files produces findings nobody may act on,
    which is worse than reviewing nothing.
    """
    return [entry for entry in entries if entry.priority > 0][:limit]
