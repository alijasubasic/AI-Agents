"""Self-improving: an evaluator-optimizer loop that refuses to fool itself.

The optimizer sees a tuning split; acceptance is decided on a holdout it never
sees. A prompt that improved only on the cases it was shown has learned those
cases, and the loop reports that rather than counting it as progress.
"""

from agents.self_improving.fixtures import BASELINE_PROMPT, CASES, build_task
from agents.self_improving.loop import ImprovementLoop, PromptRunner
from agents.self_improving.models import (
    CaseOutcome,
    Critique,
    Decision,
    Evaluation,
    ImprovementRun,
    Iteration,
    PromptProposal,
    PromptVersion,
    Split,
    TaskCase,
)
from agents.self_improving.task import PromptTask, normalise, score_exact

__all__ = [
    "BASELINE_PROMPT",
    "CASES",
    "CaseOutcome",
    "Critique",
    "Decision",
    "Evaluation",
    "ImprovementLoop",
    "ImprovementRun",
    "Iteration",
    "PromptProposal",
    "PromptRunner",
    "PromptTask",
    "PromptVersion",
    "Split",
    "TaskCase",
    "build_task",
    "normalise",
    "score_exact",
]
