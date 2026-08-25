"""The supervisor: supervises every other agent and writes the morning brief.

The codex is executable, not a prompt. The verdict on any decision is the
strictest of every reviewer's opinion, so oversight can only ever tighten.
"""

from agents.supervisor.agent import SupervisorAgent
from agents.supervisor.codex import ARTICLES, apply_codex, codex_verdict
from agents.supervisor.models import (
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
from agents.supervisor.pipeline import run_all
from agents.supervisor.reporting import (
    build_report,
    build_sheets,
    outbound_queue,
    render_markdown,
    tasks_from_reviews,
)
from agents.supervisor.spreadsheet import CsvWorkbook, Sheet, XlsxWorkbook, build_writer

__all__ = [
    "ARTICLES",
    "SupervisorAgent",
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
