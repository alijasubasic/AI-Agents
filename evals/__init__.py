"""Scored test cases for every agent.

Two layers, kept apart on purpose. `Layer.LOGIC` scores deterministic code and
runs free in CI; `Layer.JUDGEMENT` scores the model and needs a live key.
Mixing them produces a number that looks like quality and measures neither.
"""

from evals.models import (
    CaseResult,
    EvalCase,
    EvalReport,
    Expectation,
    Layer,
    Score,
    SuiteResult,
)
from evals.registry import REGISTRY, case, load_all
from evals.runner import render_table, run, run_case

__all__ = [
    "REGISTRY",
    "CaseResult",
    "EvalCase",
    "EvalReport",
    "Expectation",
    "Layer",
    "Score",
    "SuiteResult",
    "case",
    "load_all",
    "render_table",
    "run",
    "run_case",
]
