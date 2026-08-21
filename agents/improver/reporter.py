"""Writing `docs/improvement-log.md`.

Rendered from the run record, with no model involved, for the reason that
recurs throughout this repository: a generated summary is a way for the prose
to disagree with what actually happened.

The log is written to be read by somebody deciding whether to merge, which
shapes what goes in it. **Refused and reverted patches are reported as
prominently as applied ones** — a log showing only successes is a log that
cannot be used to judge whether the agent is worth running.
"""

from __future__ import annotations

from agents.improver.models import (
    ImprovementRun,
    PatchAttempt,
    Reviewer,
    Severity,
)

LOG_PATH = "docs/improvement-log.md"


def _attempt_line(attempt: PatchAttempt) -> str:
    finding = attempt.patch.finding
    return (
        f"- **{finding.title}** — `{finding.path}`  \n"
        f"  {finding.severity.label} · {finding.reviewer.value} · "
        f"`{attempt.patch.branch}`  \n"
        f"  {attempt.reason}"
    )


def render_entry(run: ImprovementRun) -> str:
    """One run's section of the log."""
    lines = [
        f"## {run.run_date.isoformat()}",
        "",
        f"Reviewed {len(run.reviewed)} file(s), {len(run.findings)} raw findings, "
        f"{len(run.worklist)} on the worklist, {len(run.nits)} nits collected.",
        "",
        f"**{len(run.applied)} applied · {len(run.reverted)} reverted · "
        f"{len(run.refused)} refused · ${run.cost_usd:.4f}**",
        "",
    ]

    if run.applied:
        lines += ["### Applied", "", "Each on its own branch, awaiting review.", ""]
        lines += [_attempt_line(attempt) for attempt in run.applied]
        lines.append("")

    if run.reverted:
        lines += [
            "### Attempted and reverted",
            "",
            "Written, failed a gate, discarded. Recorded so the same finding is "
            "not tried again next week without something changing first.",
            "",
        ]
        lines += [_attempt_line(attempt) for attempt in run.reverted]
        lines.append("")

    if run.refused:
        lines += [
            "### Refused before writing",
            "",
            "A safety rule stopped these before anything reached the workspace.",
            "",
        ]
        lines += [_attempt_line(attempt) for attempt in run.refused]
        lines.append("")

    if run.nits:
        lines += [
            "### Nits",
            "",
            "Collected rather than patched: a branch per nit produces ten reviews nobody wants.",
            "",
        ]
        lines += [f"- `{nit.path}` — {nit.title}" for nit in sorted(run.nits, key=lambda n: n.path)]
        lines.append("")

    counts = _reviewer_counts(run)
    if counts:
        lines += ["### By reviewer", "", "| Reviewer | Findings |", "|---|---|"]
        lines += [f"| {reviewer} | {count} |" for reviewer, count in counts]
        lines.append("")

    if run.halted_reason:
        lines += [f"_Run halted: {run.halted_reason}_", ""]

    return "\n".join(lines).rstrip() + "\n"


def _reviewer_counts(run: ImprovementRun) -> list[tuple[str, int]]:
    counts: dict[str, int] = {reviewer.value: 0 for reviewer in Reviewer}
    for finding in run.findings:
        counts[finding.reviewer.value] += 1
    return [(name, count) for name, count in sorted(counts.items()) if count]


def render_log(runs: list[ImprovementRun]) -> str:
    """The whole log, newest run first."""
    header = [
        "# Improvement log",
        "",
        "Written by `make improve`. Every run appends a section: what was found,",
        "what was patched, what was refused, and what it cost.",
        "",
        "Nothing here has been merged. Each applied patch is a branch waiting for",
        "a person to look at it.",
        "",
    ]
    entries = [render_entry(run) for run in sorted(runs, key=lambda r: r.run_date, reverse=True)]
    return "\n".join(header) + "\n" + "\n".join(entries)


def summarise(run: ImprovementRun) -> str:
    """One line for a pull request title or a chat message."""
    return (
        f"{run.run_date.isoformat()}: {len(run.applied)} patch(es) on branches, "
        f"{len(run.reverted)} reverted, {len(run.refused)} refused, "
        f"{len(run.nits)} nits — ${run.cost_usd:.4f}"
    )


def worst_unfixed(run: ImprovementRun) -> list[str]:
    """Findings the run could not act on, worst first.

    The most useful thing in the report for a person: these are the problems
    the agent knows about and cannot fix by itself, which is exactly the list
    somebody should be working from.
    """
    unfixed = [
        attempt.patch.finding
        for attempt in run.attempts
        if not attempt.succeeded and attempt.patch.finding.title
    ]
    unfixed.sort(key=lambda finding: (-int(finding.severity), finding.path))
    return [
        f"[{finding.severity.label}] {finding.path}: {finding.title}"
        for finding in unfixed
        if finding.severity >= Severity.MAJOR
    ]
