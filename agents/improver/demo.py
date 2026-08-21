"""Runnable demonstration of the improvement agent.

    python -m agents.improver.demo

Two halves, and the split between them is itself the point.

The **scan** is run against this repository for real, because reading files
cannot hurt anything. What it prints is the genuine ranking of what the
improver would look at next.

The **patch** stage runs entirely in memory against a synthetic file. A demo of
a code-modifying agent that modified the repository it was demonstrating in
would be an unpleasant surprise, and "it only creates a branch" is not
reassurance enough to rely on.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from agents.improver.models import ImprovementRun, Patch, PatchStatus
from agents.improver.pipeline import ImprovementPipeline
from agents.improver.reporter import render_entry, summarise, worst_unfixed
from agents.improver.safety import (
    MAX_PATCH_CHARS,
    check_patch,
)
from agents.improver.scanner import candidates, scan
from agents.improver.scripted import (
    DISCOUNT_BUG,
    SYNTHETIC_INDEX,
    patcher_provider,
    reviewer_providers,
    workspace,
)
from core.config import Settings
from core.console import configure_stdout

RUN_DATE = date(2026, 3, 6)

_MARK = {
    PatchStatus.APPLIED: " applied ",
    PatchStatus.REVERTED: " reverted",
    PatchStatus.REFUSED: " refused ",
}


def run(settings: Settings | None = None) -> ImprovementRun:
    """Run the pipeline against the in-memory workspace."""
    return ImprovementPipeline(
        workspace=workspace(RUN_DATE),
        reviewer_providers=reviewer_providers(),
        patcher_provider=patcher_provider(),
        settings=settings or Settings.from_env(),
        run_date=RUN_DATE,
        review_limit=1,
    ).run(SYNTHETIC_INDEX)


def _print_scan(root: Path) -> None:
    index = scan(root)
    eligible = candidates(index, limit=5)
    excluded = [entry for entry in index if entry.priority == 0.0]

    print(f"\n{'=' * 78}")
    print(f"Scanned {len(index)} source files in {root.resolve().name}/ (read-only)")
    print("=" * 78)
    print(f"  {len(excluded)} excluded as protected or part of the improver itself")
    print("\n  next in line for review:")
    for entry in eligible:
        print(f"    {entry.priority:>4.1f}  {entry.path:<44} {', '.join(entry.priority_reasons)}")


def _print_run(result: ImprovementRun) -> None:
    print(f"\n{'=' * 78}")
    print("Reviewer crew on a synthetic file (in memory, nothing on disk)")
    print("=" * 78)
    print(
        f"  {len(result.findings)} raw findings -> {len(result.worklist)} on the "
        f"worklist, {len(result.nits)} nits collected"
    )

    dropped = len(result.findings) - len(result.worklist) - len(result.nits)
    if dropped:
        print(f"  {dropped} dropped: the quoted anchor was not in the file")

    print("\n  worklist:")
    for finding in result.worklist:
        print(f"    [{finding.severity.label:<7}] {finding.reviewer.value:<13} {finding.title}")

    print("\n  patches:")
    for attempt in result.attempts:
        print(f"    [{_MARK[attempt.status]}] {attempt.patch.finding.title}")
        print(f"                 {attempt.reason}")

    print(f"\n  {summarise(result)}")


def _print_safety() -> None:
    """Show the rules refusing patches the pipeline never produced.

    The pipeline cannot generate these: a finding's path is forced to the file
    under review, and a patch may only touch the path its finding named. This
    is the layer underneath that, demonstrated directly.
    """
    probes: list[tuple[str, Patch]] = [
        (
            "a patch that would weaken a test",
            Patch(
                finding=DISCOUNT_BUG,
                branch="improve/probe-a",
                changes={"tests/test_cost.py": "# relaxed\n"},
            ),
        ),
        (
            "a patch that would edit the improver itself",
            Patch(
                finding=DISCOUNT_BUG,
                branch="improve/probe-b",
                changes={"agents/improver/safety.py": "MAX_PATCHES_PER_RUN = 999\n"},
            ),
        ),
        (
            "a patch that would loosen CI",
            Patch(
                finding=DISCOUNT_BUG,
                branch="improve/probe-c",
                changes={".github/workflows/ci.yml": "# no tests\n"},
            ),
        ),
        (
            "a rewrite dressed as a fix",
            Patch(
                finding=DISCOUNT_BUG,
                branch="improve/probe-d",
                changes={"core/pricing.py": "x" * (MAX_PATCH_CHARS + 1)},
            ),
        ),
    ]

    print(f"\n{'=' * 78}")
    print("What the safety rules refuse")
    print("=" * 78)
    for label, patch in probes:
        violations = check_patch(patch)
        print(f"\n  {label}:")
        for violation in violations:
            print(f"    refused - {violation}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("improver demo")
    print(f"mode={settings.mode}  model={settings.model}  run date {RUN_DATE}")

    _print_scan(Path("."))

    result = run(settings)
    _print_run(result)
    _print_safety()

    unfixed = worst_unfixed(result)
    print(f"\n{'=' * 78}")
    if unfixed:
        print("Left for a person:")
        for line in unfixed:
            print(f"  {line}")

    print("\nLog entry that would be appended to docs/improvement-log.md:\n")
    for line in render_entry(result).splitlines()[:14]:
        print(f"  {line}")

    print(
        f"\n{'=' * 78}\n"
        "Nothing was merged and nothing on disk changed. A real run leaves one\n"
        "branch per applied patch and a report; a person decides what happens."
    )


if __name__ == "__main__":
    main()
