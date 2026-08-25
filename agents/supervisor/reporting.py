"""Turning a day of reviews into a morning brief.

Two outputs from the same data: Markdown for reading, sheets for a spreadsheet.
Both are rendered from the `DailyReport` by plain code — no model is involved,
so the prose cannot disagree with the numbers beside it.

The brief answers two questions and nothing else: what happened yesterday, and
what needs a person today. Anything that does not serve one of those is noise
at eight in the morning.
"""

from __future__ import annotations

from datetime import date, timedelta

from agents.supervisor.models import (
    DailyReport,
    Review,
    Severity,
    TaskItem,
    TaskPriority,
    Verdict,
)
from agents.supervisor.spreadsheet import Sheet

#: Escalation wording that means someone is waiting on a person right now.
_URGENT_MARKERS = ("urgent", "immediate", "hostile", "complaint", "injection", "legal")


def _priority_for(review: Review) -> TaskPriority:
    """How soon a held or blocked decision needs attention."""
    haystack = " ".join(review.reasons + review.decision.escalation_reasons).lower()
    if any(marker in haystack for marker in _URGENT_MARKERS):
        return TaskPriority.URGENT
    if review.verdict is Verdict.BLOCKED:
        return TaskPriority.HIGH
    if review.breaches:
        return TaskPriority.HIGH
    return TaskPriority.NORMAL


def tasks_from_reviews(reviews: list[Review]) -> list[TaskItem]:
    """Derive today's work from yesterday's unfinished decisions.

    Only decisions that did not go through produce tasks. An approved decision
    is done, and listing it as a task would bury the four things that are not.
    """
    tasks: list[TaskItem] = []

    for review in reviews:
        if review.verdict is Verdict.APPROVED:
            continue

        decision = review.decision
        verb = "Unblock" if review.verdict is Verdict.BLOCKED else "Review"
        tasks.append(
            TaskItem(
                id=f"task-{decision.id}",
                title=f"{verb}: {decision.subject}",
                priority=_priority_for(review),
                origin_agent=decision.agent,
                source_decision=decision.id,
                why="; ".join(review.reasons[:3]) or review.verdict.label,
            )
        )

    return sorted(tasks, key=lambda task: task.sort_key)


def build_report(
    reviews: list[Review], *, generated_for: date, covering: date | None = None
) -> DailyReport:
    """Assemble the brief for one morning."""
    return DailyReport(
        generated_for=generated_for,
        covering=covering or generated_for - timedelta(days=1),
        reviews=reviews,
        tasks=tasks_from_reviews(reviews),
        total_cost_usd=sum(r.decision.cost_usd for r in reviews),
    )


# --- Markdown -----------------------------------------------------------


def render_markdown(report: DailyReport) -> str:
    """The brief as Markdown."""
    lines = [
        f"# Morning brief — {report.generated_for:%A %d %B %Y}",
        "",
        f"Covering {report.covering:%A %d %B}.",
        "",
        "## Yesterday",
        "",
        f"- **{len(report.reviews)}** decisions reviewed",
        f"- **{len(report.approved)}** went ahead automatically ({report.autonomy_rate:.0%})",
        f"- **{len(report.held)}** held for a person",
        f"- **{len(report.blocked)}** blocked outright",
        f"- **${report.total_cost_usd:.4f}** spent",
        "",
    ]

    if report.blocked:
        lines += ["### Blocked", ""]
        for review in report.blocked:
            lines.append(f"- **{review.decision.subject}** ({review.decision.agent})")
            lines += [f"  - {reason}" for reason in review.reasons]
        lines.append("")

    if report.held:
        lines += ["### Held for review", ""]
        for review in report.held:
            lines.append(f"- **{review.decision.subject}** ({review.decision.agent})")
            lines += [f"  - {reason}" for reason in review.reasons[:3]]
        lines.append("")

    lines += ["## Today", ""]
    if report.tasks:
        for task in report.tasks:
            lines.append(f"- `{task.priority.value}` **{task.title}** — {task.why}")
    else:
        lines.append("Nothing outstanding. Everything yesterday cleared on its own.")

    findings = report.all_findings
    if findings:
        counts: dict[str, int] = {}
        for finding in findings:
            counts[f"{finding.article} {finding.title}"] = (
                counts.get(f"{finding.article} {finding.title}", 0) + 1
            )
        lines += ["", "## Codex", "", "| Article | Times raised |", "|---|---|"]
        lines += [f"| {article} | {count} |" for article, count in sorted(counts.items())]

    return "\n".join(lines)


# --- Sheets -------------------------------------------------------------


def build_sheets(report: DailyReport) -> list[Sheet]:
    """The brief as spreadsheet tabs."""
    summary = Sheet(
        name="Summary",
        columns=["Metric", "Value"],
        rows=[
            ["Brief for", report.generated_for.isoformat()],
            ["Covering", report.covering.isoformat()],
            ["Decisions reviewed", str(len(report.reviews))],
            ["Approved automatically", str(len(report.approved))],
            ["Held for a person", str(len(report.held))],
            ["Blocked", str(len(report.blocked))],
            ["Autonomy rate", f"{report.autonomy_rate:.0%}"],
            ["Open tasks today", str(len(report.tasks))],
            ["Cost (USD)", f"{report.total_cost_usd:.6f}"],
        ],
    )

    decisions = Sheet(
        name="Decisions",
        columns=["ID", "Agent", "Action", "Subject", "Verdict", "Reasons", "Cost USD"],
        rows=[
            [
                review.decision.id,
                review.decision.agent,
                review.decision.kind.value,
                review.decision.subject,
                review.verdict.label,
                " | ".join(review.reasons),
                f"{review.decision.cost_usd:.6f}",
            ]
            for review in report.reviews
        ],
    )

    tasks = Sheet(
        name="Tasks today",
        columns=["ID", "Priority", "Task", "Owner", "From agent", "Why", "Decision"],
        rows=[
            [
                task.id,
                task.priority.value,
                task.title,
                task.owner,
                task.origin_agent,
                task.why,
                task.source_decision or "",
            ]
            for task in report.tasks
        ],
    )

    codex = Sheet(
        name="Codex findings",
        columns=["Decision", "Article", "Title", "Severity", "Detail", "Verdict"],
        rows=[
            [
                review.decision.id,
                finding.article,
                finding.title,
                Severity(finding.severity).name.lower(),
                finding.detail,
                finding.verdict.label,
            ]
            for review in report.reviews
            for finding in review.findings
        ],
    )

    return [summary, decisions, tasks, codex]


def outbound_queue(report: DailyReport) -> list[Review]:
    """Approved decisions that actually send something.

    Kept separate from the brief: this is the list of things that went out
    without a person seeing them, which is the number worth watching over time.
    """
    return [
        review
        for review in report.approved
        if review.decision.kind.is_outbound and review.decision.outbound_text
    ]
