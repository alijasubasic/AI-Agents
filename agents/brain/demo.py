"""The whole system, running together, supervised.

    python -m agents.brain.demo

Drives all four specialist agents over their fixtures, adapts every outcome
into a decision, puts each one through the codex and the reviewing model, then
writes the morning brief as Markdown and as a spreadsheet.

No API key, no network. Output goes to `briefs/` (git-ignored).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from agents.brain.models import DailyReport, Verdict
from agents.brain.pipeline import run_all
from agents.brain.reporting import build_report, build_sheets, outbound_queue, render_markdown
from agents.brain.scripted import judge_provider
from agents.brain.spreadsheet import build_writer
from agents.brain.supervisor import BrainAgent
from core.config import Settings
from core.console import configure_stdout

#: The morning the brief is written for. Fixed so the demo is reproducible.
BRIEF_DATE = date(2026, 3, 6)

OUTPUT_DIR = Path("briefs")

_MARK = {
    Verdict.APPROVED: "  ok   ",
    Verdict.HOLD_FOR_HUMAN: " HOLD  ",
    Verdict.BLOCKED: " BLOCK ",
}


def run(settings: Settings | None = None) -> DailyReport:
    """Run every agent, supervise the results, and build the brief."""
    settings = settings or Settings.from_env()

    decisions = run_all(settings)
    brain = BrainAgent(provider=judge_provider(decisions), settings=settings)
    reviews = brain.review_all(decisions)

    return build_report(reviews, generated_for=BRIEF_DATE)


def _print(report: DailyReport) -> None:
    print(f"\n{'=' * 78}")
    print(f"Decisions reviewed by the brain ({len(report.reviews)})")
    print("=" * 78)

    for review in report.reviews:
        decision = review.decision
        print(f"[{_MARK[review.verdict]}] {decision.agent:<16} {decision.subject[:44]}")
        for reason in review.reasons:
            print(f"            - {reason}")

    print(f"\n{'=' * 78}")
    print(
        f"{len(report.approved)} approved | {len(report.held)} held | "
        f"{len(report.blocked)} blocked | autonomy {report.autonomy_rate:.0%} | "
        f"${report.total_cost_usd:.4f}"
    )

    queue = outbound_queue(report)
    print(f"\nWent out with no human involved: {len(queue)}")
    for review in queue:
        print(f"  -> {review.decision.recipient}: {review.decision.subject[:52]}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("brain demo - every agent, supervised")
    print(f"mode={settings.mode}  model={settings.model}  brief for {BRIEF_DATE}")

    report = run(settings)
    _print(report)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = OUTPUT_DIR / f"{BRIEF_DATE:%Y-%m-%d}-brief.md"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    sheets = build_sheets(report)
    written = build_writer("csv").write(sheets, OUTPUT_DIR / f"{BRIEF_DATE:%Y-%m-%d}")

    print(f"\n{'=' * 78}")
    print("Morning brief written:")
    print(f"  {markdown_path}")
    for path in written:
        print(f"  {path}")
    print(
        "\nThe verdict on every decision is the strictest of the codex and the\n"
        "reviewing model. Neither can loosen what the other tightened, so adding\n"
        "the brain can only make the system more conservative."
    )


if __name__ == "__main__":
    main()
