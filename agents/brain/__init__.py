"""The brain: supervises every other agent and writes the morning brief.

The codex is executable, not a prompt. The verdict on any decision is the
strictest of every reviewer's opinion, so oversight can only ever tighten.
"""

from agents.brain.codex import ARTICLES, apply_codex, codex_verdict
from agents.brain.models import (
    CodexFinding,
    DailyReport,
    Decision,
    DecisionKind,
    Judgement,
    Review,
    Severity,
    TaskItem,
    TaskPriority,
    Verdict,
)
from agents.brain.pipeline import run_all
from agents.brain.reporting import (
    build_report,
    build_sheets,
    outbound_queue,
    render_markdown,
    tasks_from_reviews,
)
from agents.brain.spreadsheet import CsvWorkbook, Sheet, XlsxWorkbook, build_writer
from agents.brain.supervisor import BrainAgent

__all__ = [
    "ARTICLES",
    "BrainAgent",
    "CodexFinding",
    "CsvWorkbook",
    "DailyReport",
    "Decision",
    "DecisionKind",
    "Judgement",
    "Review",
    "Severity",
    "Sheet",
    "TaskItem",
    "TaskPriority",
    "Verdict",
    "XlsxWorkbook",
    "apply_codex",
    "build_report",
    "build_sheets",
    "build_writer",
    "codex_verdict",
    "outbound_queue",
    "render_markdown",
    "run_all",
    "tasks_from_reviews",
]
