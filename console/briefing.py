"""Turning the morning brief into something a person can see and hear.

Three renderings of one `DailyReport`, none of which involves a model:

* `build_utterances` — the briefing as spoken and displayed lines
* `build_overlay_state` — what the HUD shows
* `build_notes` — what goes into the Obsidian vault

Speech and display are generated separately rather than sharing one string.
"2 of 7 (29%)" is fine in a table and unintelligible read aloud, and a briefing
that sounds like a spreadsheet is one people stop listening to.
"""

from __future__ import annotations

from datetime import date

from agents.supervisor.models import DailyReport, Review, Verdict
from console.models import (
    Channel,
    OverlayCard,
    OverlayState,
    Priority,
    Utterance,
    VaultNote,
)

_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)

_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}


def spoken_number(value: int) -> str:
    """Small numbers as words. Larger ones stay as digits, which read fine."""
    return _ONES[value] if 0 <= value <= 20 else str(value)


def spoken_date(day: date) -> str:
    """A date as someone would say it.

    Built by hand rather than with a `%-d` format code: that directive does not
    exist on Windows, and this repository is developed there.
    """
    suffix = _ORDINAL_SUFFIX.get(day.day, "th")
    return f"{day:%A} the {day.day}{suffix} of {day:%B}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def build_utterances(report: DailyReport) -> list[Utterance]:
    """The briefing, line by line.

    Only what needs a person is spoken in detail. Reading out seven approved
    decisions trains the listener to stop paying attention by the third, which
    is precisely when the blocked one arrives.
    """
    lines: list[Utterance] = [
        Utterance(
            id="greeting",
            display_text=f"Morning brief — {report.generated_for:%A %d %B}",
            spoken_text=(
                f"Good morning. Here is the brief for {spoken_date(report.generated_for)}."
            ),
        ),
        Utterance(
            id="summary",
            display_text=(
                f"{len(report.reviews)} decisions · {len(report.approved)} approved · "
                f"{len(report.held)} held · {len(report.blocked)} blocked"
            ),
            spoken_text=(
                # Capitalised because it opens a sentence: spoken_number returns
                # a bare word, and "seventeen decisions were reviewed" reads as
                # a fragment anywhere this text is also shown.
                f"{spoken_number(len(report.reviews)).capitalize()} decisions were "
                f"reviewed. "
                f"{spoken_number(len(report.approved)).capitalize()} went ahead on "
                f"their own, "
                f"{spoken_number(len(report.held))} are waiting for you, and "
                f"{spoken_number(len(report.blocked))} "
                f"{_plural(len(report.blocked), 'was', 'were')} blocked."
            ),
        ),
    ]

    for review in report.blocked:
        reason = review.reasons[0] if review.reasons else "No reason recorded."
        lines.append(
            Utterance(
                id=f"blocked-{review.decision.id}",
                display_text=f"BLOCKED — {review.decision.subject}",
                spoken_text=f"Blocked: {review.decision.subject}. {reason}",
                priority=Priority.ALERT,
                source_decision=review.decision.id,
            )
        )

    urgent = [task for task in report.tasks if task.priority.value == "urgent"]
    for task in urgent:
        lines.append(
            Utterance(
                id=f"urgent-{task.id}",
                display_text=f"URGENT — {task.title}",
                spoken_text=f"Urgent: {task.title}.",
                priority=Priority.ATTENTION,
                source_decision=task.source_decision,
            )
        )

    remaining = len(report.tasks) - len(urgent)
    if remaining > 0:
        lines.append(
            Utterance(
                id="remaining-tasks",
                display_text=f"{remaining} further {_plural(remaining, 'task')} today",
                spoken_text=(
                    f"There {_plural(remaining, 'is', 'are')} "
                    f"{spoken_number(remaining)} further "
                    f"{_plural(remaining, 'task')} on the list."
                ),
            )
        )

    lines.append(
        Utterance(
            id="cost",
            display_text=f"${report.total_cost_usd:.4f} spent",
            channel=Channel.DISPLAY,
        )
    )
    return lines


def build_overlay_state(report: DailyReport) -> OverlayState:
    """What the HUD renders.

    Ordered by how much attention each decision needs: blocked first, then
    held, then the ones that went through. A display sorted by time buries the
    two things worth looking at.
    """
    ordered: list[Review] = [*report.blocked, *report.held, *report.approved]

    return OverlayState(
        heading=f"Morning brief — {report.generated_for:%A %d %B %Y}",
        subheading=f"covering {report.covering:%A %d %B}",
        approved=len(report.approved),
        held=len(report.held),
        blocked=len(report.blocked),
        autonomy_rate=report.autonomy_rate,
        cost_usd=report.total_cost_usd,
        cards=[
            OverlayCard(
                decision_id=review.decision.id,
                agent=review.decision.agent,
                subject=review.decision.subject,
                verdict=review.verdict,
                reasons=review.reasons,
                recipient=review.decision.recipient,
            )
            for review in ordered
        ],
        tasks=[f"[{task.priority.value}] {task.title}" for task in report.tasks],
        utterances=build_utterances(report),
    )


# --- Obsidian notes -----------------------------------------------------

_VERDICT_TAG = {
    Verdict.APPROVED: "approved",
    Verdict.HOLD_FOR_HUMAN: "held",
    Verdict.BLOCKED: "blocked",
}


def _brief_slug(report: DailyReport) -> str:
    return f"{report.generated_for.isoformat()} Brief"


def _decision_note(review: Review, brief_slug: str) -> VaultNote:
    """One decision, with links to everything that touched it.

    The links are the point. Each one names the agent, each codex article that
    fired, and the day's brief, so Obsidian's backlinks pane answers questions
    nobody built a view for: every decision A2 has ever blocked, everything
    call-intake produced last Tuesday.
    """
    decision = review.decision
    links = [f"Agent {decision.agent}", brief_slug]
    links += [f"{finding.article} {finding.title}" for finding in review.findings]

    body_lines = [decision.summary or "_No summary recorded._", ""]
    if review.reasons:
        body_lines += ["## Why", ""]
        body_lines += [f"- {reason}" for reason in review.reasons]
        body_lines.append("")

    if decision.outbound_text:
        status = (
            "This text was sent."
            if review.verdict is Verdict.APPROVED
            else "This text was **not** sent."
        )
        body_lines += ["## Draft", "", status, "", "```text", decision.outbound_text, "```", ""]

    frontmatter: dict[str, str | int | float | bool | list[str]] = {
        "type": "decision",
        "agent": decision.agent,
        "action": decision.kind.value,
        "verdict": _VERDICT_TAG[review.verdict],
        "cost_usd": round(decision.cost_usd, 6),
        "tags": ["agent-decision", _VERDICT_TAG[review.verdict]],
    }

    # Omitted rather than written empty: Obsidian's Dataview treats `date: ""`
    # as a present-but-unparseable value, which is worse than an absent key.
    occurred = decision_date(review)
    if occurred:
        frontmatter["date"] = occurred

    return VaultNote(
        slug=decision.id,
        folder="Decisions",
        title=decision.subject,
        frontmatter=frontmatter,
        body="\n".join(body_lines).strip(),
        links=links,
    )


def decision_date(review: Review) -> str:
    """The decision's own timestamp where it has one, otherwise empty."""
    occurred = review.decision.occurred_at
    return occurred.date().isoformat() if occurred else ""


def build_notes(report: DailyReport) -> list[VaultNote]:
    """Every note this brief writes into the vault.

    One note per decision, one per codex article that fired, and one for the
    brief itself. Article notes are created rather than left as unresolved
    links so that opening one shows a description alongside its backlinks.
    """
    brief_slug = _brief_slug(report)
    notes = [_decision_note(review, brief_slug) for review in report.reviews]

    seen: dict[str, str] = {}
    for finding in report.all_findings:
        seen.setdefault(f"{finding.article} {finding.title}", finding.detail)

    notes += [
        VaultNote(
            slug=name,
            folder="Codex",
            title=name,
            frontmatter={"type": "codex-article", "tags": ["codex"]},
            body=(
                f"Codex article raised by the supervising agent.\n\n"
                f"Most recent example:\n\n> {example}\n\n"
                f"Backlinks below list every decision this article has been "
                f"raised on."
            ),
            links=[brief_slug],
        )
        for name, example in sorted(seen.items())
    ]

    task_lines = [
        f"- `{task.priority.value}` {task.title}"
        + (f" → [[{task.source_decision}]]" if task.source_decision else "")
        for task in report.tasks
    ]

    notes.append(
        VaultNote(
            slug=brief_slug,
            folder="Briefs",
            title=f"Morning brief — {report.generated_for:%A %d %B %Y}",
            frontmatter={
                "type": "brief",
                "date": report.generated_for.isoformat(),
                "covering": report.covering.isoformat(),
                "reviewed": len(report.reviews),
                "approved": len(report.approved),
                "held": len(report.held),
                "blocked": len(report.blocked),
                "cost_usd": round(report.total_cost_usd, 6),
                "tags": ["brief"],
            },
            body="\n".join(
                [
                    f"Covering {report.covering:%A %d %B}.",
                    "",
                    "## Today",
                    "",
                    *(task_lines or ["Nothing outstanding."]),
                ]
            ),
            links=[review.decision.id for review in report.blocked + report.held],
        )
    )

    return notes
