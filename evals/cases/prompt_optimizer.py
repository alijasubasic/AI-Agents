"""Eval cases for the prompt-optimizer loop.

The loop's value is entirely in what it refuses to accept, so that is what
these cases measure.
"""

from __future__ import annotations

from agents.prompt_optimizer import demo
from agents.prompt_optimizer.fixtures import BASELINE_PROMPT, CASES, build_task
from agents.prompt_optimizer.loop import OptimizerLoop
from agents.prompt_optimizer.models import Decision, Split
from agents.prompt_optimizer.scripted import (
    critic_provider,
    optimizer_provider,
    scripted_runner,
)
from agents.prompt_optimizer.task import PromptTask, score_exact
from core.config import Settings
from evals.models import Expectation, Layer, Score
from evals.registry import case
from evals.scoring import combine, contains_all, equals, is_true

AGENT = "prompt-optimizer"


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def _run(**overrides):
    base = {
        "task": build_task(),
        "runner": scripted_runner,
        "critic_provider": critic_provider(),
        "optimizer_provider": optimizer_provider(),
        "settings": _settings(),
        "max_iterations": 3,
    }
    return OptimizerLoop(**{**base, **overrides}).run()


# --- The split ----------------------------------------------------------


@case(
    id="optimizer-holdout-is-never-shown-to-the-critic",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="No holdout case reaches the critic's prompt.",
)
def _() -> Score:
    critic = critic_provider()
    OptimizerLoop(
        task=build_task(),
        runner=scripted_runner,
        critic_provider=critic,
        optimizer_provider=optimizer_provider(),
        settings=_settings(),
        max_iterations=1,
    ).run()

    sent = " ".join(m["text"] for call in critic.calls for m in call["messages"])
    leaked = [c.id for c in build_task().holdout if c.inputs in sent or c.id in sent]
    return equals(leaked, [], label="leaked holdout cases")


@case(
    id="optimizer-holdout-is-never-shown-to-the-optimizer",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="No holdout case reaches the optimizer's prompt.",
)
def _() -> Score:
    optimizer = optimizer_provider()
    OptimizerLoop(
        task=build_task(),
        runner=scripted_runner,
        critic_provider=critic_provider(),
        optimizer_provider=optimizer,
        settings=_settings(),
        max_iterations=1,
    ).run()

    sent = " ".join(m["text"] for call in optimizer.calls for m in call["messages"])
    leaked = [c.id for c in build_task().holdout if c.inputs in sent]
    return equals(leaked, [], label="leaked holdout cases")


@case(
    id="optimizer-a-task-without-a-holdout-is-refused",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A task offering no holdout cannot be constructed at all.",
)
def _() -> Score:
    tuning_only = [c for c in CASES if c.split is Split.TUNING]
    try:
        PromptTask(name="t", cases=tuning_only, baseline_prompt=BASELINE_PROMPT)
    except ValueError as exc:
        return contains_all(str(exc), ["holdout"], label="error")
    return Score.miss("a task with no holdout was accepted")


# --- The gate -----------------------------------------------------------


@case(
    id="optimizer-real-gain-is-accepted",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A version better on both splits is accepted.",
)
def _() -> Score:
    result = _run()
    v1 = result.iterations[1]
    return combine(
        equals(v1.decision, Decision.ACCEPTED, label="decision"),
        is_true(v1.holdout.score > result.iterations[0].holdout.score, label="holdout rose"),
    )


@case(
    id="optimizer-memorisation-is-rejected",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Perfect on the cases it saw, unchanged on the ones it did not.",
)
def _() -> Score:
    v2 = _run().iterations[2]
    return combine(
        equals(v2.tuning.score, 1.0, label="tuning"),
        equals(v2.decision, Decision.REJECTED_NO_GAIN, label="decision"),
        is_true(v2.overfit_gap > 0, label="overfit gap positive"),
    )


@case(
    id="optimizer-regression-is-rolled-back",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A version that lowers the holdout score is rejected.",
)
def _() -> Score:
    v3 = _run().iterations[3]
    return combine(
        equals(v3.decision, Decision.REJECTED_REGRESSION, label="decision"),
        contains_all(v3.reason, ["fell"], label="reason"),
    )


@case(
    id="optimizer-proposals-build-on-the-best-accepted-version",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A rejected version is not the parent of the next attempt.",
)
def _() -> Score:
    parents = [it.version.parent for it in _run().iterations[1:]]
    return equals(parents, [0, 1, 1], label="parents")


@case(
    id="optimizer-the-baseline-survives-a-failed-run",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="When nothing is accepted, the starting prompt is still the answer.",
)
def _() -> Score:
    result = _run(
        runner=lambda version, cases: (
            {c.id: c.expected for c in cases} if version.number == 0 else {}
        )
    )
    return combine(
        equals(result.accepted_count, 0, label="accepted"),
        is_true(result.best is result.baseline, label="best is the baseline"),
        equals(result.improvement, 0.0, label="improvement"),
    )


# --- Limits and scoring -------------------------------------------------


@case(
    id="optimizer-stops-at-the-cost-ceiling",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An exhausted budget halts the loop cleanly.",
)
def _() -> Score:
    result = _run(max_cost_usd=0.0001)
    return contains_all(result.halted_reason or "", ["cost budget"], label="halt reason")


@case(
    id="optimizer-a-missing-answer-scores-zero",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Not answering does not raise the average by shrinking the denominator.",
)
def _() -> Score:
    task = build_task()
    evaluation = task.evaluate(Split.HOLDOUT, {})
    return combine(
        equals(len(evaluation.outcomes), len(task.holdout), label="outcomes"),
        equals(evaluation.score, 0.0, label="score"),
    )


@case(
    id="optimizer-scoring-tolerates-formatting-not-hedging",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="'Billing.' is correct; 'probably billing' is not.",
)
def _() -> Score:
    return combine(
        equals(score_exact("Billing.", "billing"), 1.0, label="formatting"),
        equals(score_exact("probably billing", "billing"), 0.0, label="hedging"),
    )


@case(
    id="optimizer-demo-shows-every-outcome",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Accept, memorisation and regression all appear in one run.",
)
def _() -> Score:
    decisions = {it.decision for it in demo.run(_settings()).iterations[1:]}
    return equals(
        decisions,
        {Decision.ACCEPTED, Decision.REJECTED_NO_GAIN, Decision.REJECTED_REGRESSION},
        label="decisions",
    )


# --- Known gaps ---------------------------------------------------------


@case(
    id="optimizer-holdout-erodes-with-reuse",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Nothing tracks how often the holdout has been used to decide.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Every acceptance decision leaks a little information about the holdout "
        "into the surviving prompt. Over many runs the split stops being held "
        "out. A real system rotates cases or budgets decisions per split; this "
        "one does neither."
    ),
)
def _() -> Score:
    result = _run()
    return is_true(hasattr(result, "holdout_decisions_used"), label="holdout usage tracked")


@case(
    id="optimizer-scores-one-metric-only",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A prompt that improves accuracy and doubles in length still wins.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Acceptance looks at exact-match accuracy and nothing else. Latency, "
        "token cost and prompt length are invisible, so the loop will happily "
        "accept a much longer prompt for a one-case gain."
    ),
)
def _() -> Score:
    result = _run()
    grew = len(result.best.version.text) > len(result.baseline.version.text) * 1.5
    return is_true(not grew, label="length considered in acceptance")


@case(
    id="optimizer-one-run-is-one-sample",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Each version is evaluated once, so a live run cannot separate gain from noise.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Deterministic in mock mode and misleading in live mode: a single pass "
        "over four holdout cases cannot distinguish a real improvement from "
        "sampling variance. Repeated trials with a confidence interval are what "
        "this needs before anyone trusts a live number."
    ),
)
def _() -> Score:
    return is_true(hasattr(OptimizerLoop, "trials_per_version"), label="repeated trials supported")
