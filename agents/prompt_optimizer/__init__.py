"""Self-improving: an evaluator-optimizer loop that refuses to fool itself.

The optimizer sees a tuning split; acceptance is decided on a holdout it never
sees. A prompt that improved only on the cases it was shown has learned those
cases, and the loop reports that rather than counting it as progress.
"""

from agents.prompt_optimizer.fixtures import BASELINE_PROMPT, CASES, build_task
from agents.prompt_optimizer.loop import OptimizerLoop, PromptRunner
from agents.prompt_optimizer.models import (
    CaseOutcome,
    Critique,
    Decision,
    Evaluation,
    Iteration,
    OptimizerRun,
    PromptProposal,
    PromptVersion,
    Split,
    TaskCase,
)
from agents.prompt_optimizer.task import PromptTask, normalise, score_exact

__all__ = [
    "BASELINE_PROMPT",
    "CASES",
    "CaseOutcome",
    "Critique",
    "Decision",
    "Evaluation",
    "OptimizerLoop",
    "OptimizerRun",
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
