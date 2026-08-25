"""The non-negotiable rules.

Everything in this module exists to constrain the improvement agent, and it is
worth being precise about why.

An agent that writes code has one failure mode that matters more than the
rest: **writing a bad patch and then adjusting whatever would have caught it.**
A weakened assertion, a loosened lint rule, a deleted eval case. Each one makes
the next run look cleaner and the repository worse, and each one is a change a
well-meaning model can rationalise — "this test was too strict", "this rule
does not apply here".

So the code reviewer cannot touch the things that judge it. Not "is told not to";
cannot. `check_patch` runs before a patch is written anywhere and refuses on a
path match, without consulting anything.

The rules are deliberately blunt. A blunt rule that occasionally refuses a good
patch costs a human two minutes; a subtle rule with a hole in it costs the
integrity of every number in the repository.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from agents.code_reviewer.models import Patch

#: Paths the code reviewer may never modify, whatever it finds there.
#:
#: These are the checks that judge its work. It may report a problem in any of
#: them as a finding for a person to act on — that is what the reporter is for.
PROTECTED_PREFIXES: tuple[str, ...] = (
    "tests/",
    "evals/",
    ".github/",
    "docs/adr/",
)

PROTECTED_FILES: frozenset[str] = frozenset(
    {
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        ".gitignore",
        ".gitattributes",
        ".env.example",
    }
)

#: Any path segment matching this is a test directory, wherever it sits. Agent
#: tests live next to their agent rather than under tests/, and they are as
#: protected as the ones that do.
_TEST_DIR = re.compile(r"(^|/)tests?(/|$)")
_TEST_FILE = re.compile(r"(^|/)test_[^/]+\.py$")

#: The code reviewer's own package. It may analyse itself and report findings; it
#: may not patch itself. A self-modifying code reviewer is one whose safety rules
#: are editable by the thing they constrain.
SELF_PREFIX = "agents/code_reviewer/"

# --- Per-run limits -----------------------------------------------------

#: Most patches one run may apply. A run wanting more than this is not having
#: a productive day; it is doing something nobody asked for.
MAX_PATCHES_PER_RUN = 10

#: Largest single patch, in characters written. A patch bigger than this is a
#: rewrite, and a rewrite is not reviewable one finding at a time.
MAX_PATCH_CHARS = 6_000

#: Most files one patch may touch. One finding, one place.
MAX_FILES_PER_PATCH = 3

#: Cost ceiling for a whole run.
MAX_RUN_COST_USD = 5.00


def normalise(path: str) -> str:
    """Repository-relative POSIX form, so rules match on every platform.

    `removeprefix`, not `lstrip`. `lstrip("./")` strips a *set of characters*,
    so it turns `.github/workflows/ci.yml` into `github/workflows/ci.yml` and
    the `.github/` rule below stops matching — which left CI configuration
    unprotected. `PurePosixPath` already drops a leading `./`; the removeprefix
    is belt and braces.
    """
    return PurePosixPath(path.replace("\\", "/")).as_posix().removeprefix("./")


def is_protected(path: str) -> bool:
    """Whether a path is one of the checks that judge the code reviewer's work."""
    clean = normalise(path)
    return (
        clean in PROTECTED_FILES
        or clean.startswith(PROTECTED_PREFIXES)
        or bool(_TEST_DIR.search(clean))
        or bool(_TEST_FILE.search(clean))
    )


def is_self(path: str) -> bool:
    """Whether a path belongs to the code reviewer itself."""
    return normalise(path).startswith(SELF_PREFIX)


def may_modify(path: str) -> bool:
    """The single question every write goes through."""
    return not is_protected(path) and not is_self(path)


def check_patch(patch: Patch, *, applied_so_far: int = 0) -> list[str]:
    """Every rule this patch breaks. Empty means it may be written.

    Checked before anything reaches disk. Reasons accumulate rather than
    short-circuiting: a person reading a refusal should see everything wrong
    with it, not the first thing checked.
    """
    violations: list[str] = []

    for path in patch.touched:
        if is_self(path):
            violations.append(
                f"{path} is part of the code reviewer itself; changes to it go through a person"
            )
        elif is_protected(path):
            violations.append(
                f"{path} is a test, eval, or CI file; the code reviewer may not modify "
                f"what judges its work"
            )

    if not patch.changes:
        violations.append("patch changes nothing")

    if len(patch.changes) > MAX_FILES_PER_PATCH:
        violations.append(
            f"patch touches {len(patch.changes)} files, over the "
            f"{MAX_FILES_PER_PATCH}-file limit for a single finding"
        )

    if patch.size > MAX_PATCH_CHARS:
        violations.append(
            f"patch writes {patch.size:,} characters, over the "
            f"{MAX_PATCH_CHARS:,} limit; this is a rewrite, not a fix"
        )

    if applied_so_far >= MAX_PATCHES_PER_RUN:
        violations.append(
            f"{applied_so_far} patches already applied this run, at the {MAX_PATCHES_PER_RUN} limit"
        )

    outside = [
        path
        for path in patch.touched
        if patch.allowed_paths and normalise(path) not in map(normalise, patch.allowed_paths)
    ]
    if outside:
        violations.append(f"patch touches {', '.join(outside)}, which the finding did not name")

    return violations


def branch_name(run_date, slug: str) -> str:
    """`improve/<date>-<slug>`, sanitised into something git accepts.

    Truncated at a word boundary rather than at a character count. A branch
    called `...-as-a-fracti` is the sort of detail that makes a generated
    change look careless before anyone has read the diff.
    """
    words = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-").split("-")

    clean = ""
    for word in words:
        candidate = f"{clean}-{word}" if clean else word
        if len(candidate) > 40:
            break
        clean = candidate

    return f"improve/{run_date.isoformat()}-{clean or 'change'}"
