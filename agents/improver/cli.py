"""`make improve`.

    python -m agents.improver             # dry run: scan, review, report
    python -m agents.improver --apply     # also write patches, on branches

**The default stops before writing anything.** A dry run scans the repository,
runs the reviewer crew, and reports the worklist it would work from. That is
genuinely the useful half — knowing what an agent thinks is wrong is worth more
than most of the patches — and it cannot damage anything.

`--apply` is the half that writes. It needs a live API key and a clean working
tree, creates one branch per patch, and merges nothing. Everything it produces
waits for a person.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from agents.improver.models import ImprovementRun, Reviewer
from agents.improver.pipeline import ImprovementPipeline
from agents.improver.prioritizer import prioritise
from agents.improver.reporter import LOG_PATH, render_entry, summarise
from agents.improver.reviewers import ReviewerCrew
from agents.improver.safety import MAX_PATCHES_PER_RUN
from agents.improver.scanner import candidates, scan
from core.config import Settings
from core.console import configure_stdout
from core.llm import AnthropicProvider


def _live_providers(
    settings: Settings,
) -> tuple[dict[Reviewer, AnthropicProvider], AnthropicProvider]:
    """One provider per reviewer, plus one for the patcher.

    Separate instances rather than one shared: each reviewer holds its own
    conversation, and sharing a client between them would work but makes the
    per-role cost impossible to attribute.
    """
    reviewers = {reviewer: AnthropicProvider(settings) for reviewer in Reviewer}
    return reviewers, AnthropicProvider(settings)


def dry_run(root: Path, *, settings: Settings, limit: int) -> ImprovementRun:
    """Scan and review. Draft nothing, write nothing."""
    index = scan(root)
    result = ImprovementRun(run_date=date.today(), scanned=index)

    targets = candidates(index, limit=limit)
    if not targets:
        result.halted_reason = "nothing in the index was eligible for review"
        return result

    if not settings.is_live:
        result.halted_reason = (
            "reviewing needs a live model. Set AGENT_MODE=live with an "
            "ANTHROPIC_API_KEY, or read the ranking above and pick a file yourself"
        )
        return result

    reviewers, _patcher = _live_providers(settings)
    crew = ReviewerCrew(providers=reviewers, settings=settings)

    sources = {entry.path: (root / entry.path).read_text(encoding="utf-8") for entry in targets}
    for entry in targets:
        findings, cost = crew.review(entry.path, sources[entry.path], has_tests=entry.has_tests)
        result.findings.extend(findings)
        result.reviewed.append(entry.path)
        result.cost_usd += cost

    result.worklist, result.nits = prioritise(
        result.findings, {entry.path: entry for entry in index}, sources
    )
    return result


def apply_run(root: Path, *, settings: Settings, limit: int, max_patches: int) -> ImprovementRun:
    """The full pipeline against a real checkout."""
    from agents.improver.workspace import GitWorkspace

    if not settings.is_live:
        raise SystemExit(
            "--apply needs a live model. Set AGENT_MODE=live with an ANTHROPIC_API_KEY."
        )

    reviewers, patcher = _live_providers(settings)
    return ImprovementPipeline(
        workspace=GitWorkspace(root),
        reviewer_providers=reviewers,
        patcher_provider=patcher,
        settings=settings,
        max_patches=max_patches,
        review_limit=limit,
    ).run(scan(root))


def _print(result: ImprovementRun, *, applied: bool) -> None:
    print(f"\n{'=' * 78}")
    print(f"Scanned {len(result.scanned)} files, reviewed {len(result.reviewed)}")
    print("=" * 78)

    for entry in candidates(result.scanned, limit=8):
        print(f"  {entry.priority:>4.1f}  {entry.path:<44} {', '.join(entry.priority_reasons)}")

    if result.worklist:
        print(f"\n  worklist ({len(result.worklist)}):")
        for finding in result.worklist:
            print(
                f"    [{finding.severity.label:<7}] {finding.reviewer.value:<13} "
                f"{finding.path}: {finding.title}"
            )

    if result.nits:
        print(f"\n  {len(result.nits)} nits collected, not patched")

    # Printed on every run, not only on --apply. A dry run spends real money on
    # the reviewer crew, and the first live run of this CLI reported no cost at
    # all — which is precisely the number somebody wants before running it again.
    print(f"\n  {summarise(result)}")
    if applied:
        for branch in result.branches:
            print(f"    branch: {branch}")

    if result.halted_reason:
        print(f"\n  stopped: {result.halted_reason}")


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="Review this repository and propose patches.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write patches on branches. Needs a live API key and a clean tree.",
    )
    parser.add_argument("--limit", type=int, default=3, help="files to review")
    parser.add_argument(
        "--max-patches",
        type=int,
        default=MAX_PATCHES_PER_RUN,
        help=f"patches to apply, capped at {MAX_PATCHES_PER_RUN}",
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--log",
        action="store_true",
        help=f"append the run to {LOG_PATH}",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    print("improver")
    print(f"mode={settings.mode}  {'apply' if args.apply else 'dry run'}")

    if args.apply:
        result = apply_run(
            args.root, settings=settings, limit=args.limit, max_patches=args.max_patches
        )
    else:
        result = dry_run(args.root, settings=settings, limit=args.limit)

    _print(result, applied=args.apply)

    if args.log:
        log = args.root / LOG_PATH
        log.parent.mkdir(parents=True, exist_ok=True)
        existing = log.read_text(encoding="utf-8") if log.exists() else ""
        log.write_text(render_entry(result) + "\n" + existing, encoding="utf-8")
        print(f"\n  appended to {LOG_PATH}")

    print("\nNothing was merged. Every applied patch is a branch waiting for a person.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
