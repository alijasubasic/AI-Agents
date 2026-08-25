"""Tests for the evaluator-optimizer loop.

The tests that matter here are about the split: that the optimizer never sees
the holdout, and that acceptance is decided on it alone. Everything else in
this agent is bookkeeping around those two facts.
"""

from __future__ import annotations

import pytest

from agents.prompt_optimizer import demo
from agents.prompt_optimizer.fixtures import BASELINE_PROMPT, CASES, build_task
from agents.prompt_optimizer.loop import OptimizerLoop
from agents.prompt_optimizer.models import (
    Critique,
    Decision,
    PromptProposal,
    PromptVersion,
    Split,
    TaskCase,
)
from agents.prompt_optimizer.scripted import (
    ANSWERS,
    critic_provider,
    optimizer_provider,
    scripted_runner,
)
from agents.prompt_optimizer.task import PromptTask, normalise, score_exact
from core.config import Settings
from core.llm import MockProvider, text_response


def settings() -> Settings:
    return Settings(trace_enabled=False)


def loop(**overrides) -> OptimizerLoop:
    base = {
        "task": build_task(),
        "runner": scripted_runner,
        "critic_provider": critic_provider(),
        "optimizer_provider": optimizer_provider(),
        "settings": settings(),
        "max_iterations": 3,
    }
    return OptimizerLoop(**{**base, **overrides})


# --- Scoring ------------------------------------------------------------


def test_formatting_differences_do_not_count_as_wrong():
    assert score_exact("Billing.", "billing") == 1.0
    assert score_exact("  TECHNICAL  ", "technical") == 1.0


def test_a_hedged_answer_is_wrong():
    # "probably billing" has not answered the question that was asked.
    assert score_exact("probably billing", "billing") == 0.0


def test_normalisation_folds_punctuation_and_case():
    assert normalise("Sales!") == "sales"


def test_a_missing_answer_scores_zero_rather_than_being_skipped():
    # Dropping it would let a prompt improve its average by not responding.
    task = build_task()
    evaluation = task.evaluate(Split.HOLDOUT, {})

    assert len(evaluation.outcomes) == len(task.holdout)
    assert evaluation.score == 0.0


# --- The split ----------------------------------------------------------


def test_a_task_without_a_holdout_is_refused():
    tuning_only = [case for case in CASES if case.split is Split.TUNING]
    with pytest.raises(ValueError, match="holdout"):
        PromptTask(name="t", cases=tuning_only, baseline_prompt=BASELINE_PROMPT)


def test_a_task_needs_cases_at_all():
    with pytest.raises(ValueError, match="cases"):
        PromptTask(name="t", cases=[], baseline_prompt="p")


def test_the_critic_is_only_ever_shown_tuning_failures():
    # The whole design rests on this. A critic that has seen the holdout can
    # leak it into its advice, and the split becomes decoration.
    critic = critic_provider()
    OptimizerLoop(
        task=build_task(),
        runner=scripted_runner,
        critic_provider=critic,
        optimizer_provider=optimizer_provider(),
        settings=settings(),
        max_iterations=1,
    ).run()

    sent = " ".join(message["text"] for call in critic.calls for message in call["messages"])
    for case in build_task().holdout:
        assert case.inputs not in sent
        assert case.id not in sent


def test_the_optimizer_is_only_ever_shown_the_prompt_and_the_critique():
    optimizer = optimizer_provider()
    OptimizerLoop(
        task=build_task(),
        runner=scripted_runner,
        critic_provider=critic_provider(),
        optimizer_provider=optimizer,
        settings=settings(),
        max_iterations=1,
    ).run()

    sent = " ".join(message["text"] for call in optimizer.calls for message in call["messages"])
    for case in build_task().holdout:
        assert case.inputs not in sent


# --- The gate -----------------------------------------------------------


def test_a_real_improvement_is_accepted():
    result = loop().run()
    v1 = result.iterations[1]

    assert v1.decision is Decision.ACCEPTED
    assert v1.holdout.score > result.iterations[0].holdout.score


def test_a_version_that_learned_its_examples_is_rejected():
    # v2 is perfect on the cases it was shown and no better on the ones it was
    # not. Without the holdout it would have looked like the best of the run.
    result = loop().run()
    v2 = result.iterations[2]

    assert v2.tuning.score == 1.0
    assert v2.decision is Decision.REJECTED_NO_GAIN
    assert v2.overfit_gap > 0
    assert "learned the examples" in v2.reason


def test_a_regression_is_rejected_and_named():
    result = loop().run()
    v3 = result.iterations[3]

    assert v3.decision is Decision.REJECTED_REGRESSION
    assert "fell" in v3.reason


def test_the_best_version_is_the_accepted_one_not_the_last():
    result = loop().run()
    assert result.best is not None
    assert result.best.version.number == 1


def test_a_rejected_version_is_not_built_on():
    # Hill climbing with rollback: each proposal starts from the best accepted
    # prompt, so a bad step does not compound.
    result = loop().run()
    parents = [it.version.parent for it in result.iterations[1:]]
    assert parents == [0, 1, 1]


def test_improvement_is_measured_on_the_holdout():
    result = loop().run()
    baseline, best = result.baseline, result.best
    assert result.improvement == best.holdout.score - baseline.holdout.score


def test_the_baseline_is_kept_even_if_nothing_beats_it():
    # A run that accepts nothing still has an answer: the prompt it started
    # with.
    flat = {case.id: case.expected for case in CASES}
    result = OptimizerLoop(
        task=build_task(),
        runner=lambda version, cases: (
            {c.id: c.expected for c in cases} if version.number == 0 else {}
        ),
        critic_provider=critic_provider(),
        optimizer_provider=optimizer_provider(),
        settings=settings(),
        max_iterations=2,
    ).run()

    assert result.accepted_count == 0
    assert result.best is result.baseline
    assert result.improvement == 0.0
    assert flat  # fixture sanity


# --- Limits -------------------------------------------------------------


def test_the_loop_stops_at_the_iteration_ceiling():
    result = loop(max_iterations=1).run()
    assert len(result.iterations) == 2  # baseline plus one proposal


def test_the_loop_stops_when_the_cost_budget_is_gone():
    result = loop(max_cost_usd=0.0001).run()
    assert result.halted_reason is not None
    assert "cost budget" in result.halted_reason


def test_an_empty_proposal_halts_rather_than_being_accepted():
    empty = MockProvider(
        [text_response(PromptProposal(prompt="   ", rationale="none").model_dump_json())],
        model="claude-opus-5",
    )
    result = loop(optimizer_provider=empty).run()

    assert result.halted_reason == "the optimizer produced no usable prompt"
    assert result.accepted_count == 0


def test_a_required_minimum_gain_rejects_marginal_versions():
    result = loop(min_gain=0.5).run()
    assert result.accepted_count == 0


# --- Bookkeeping --------------------------------------------------------


def test_every_version_records_where_it_came_from():
    result = loop().run()
    for iteration in result.iterations[1:]:
        assert iteration.version.parent is not None
        assert iteration.version.rationale


def test_every_proposal_records_its_critique():
    result = loop().run()
    assert all(it.critique is not None for it in result.iterations[1:])
    assert result.iterations[0].critique is None


def test_the_scripted_tables_cover_every_case():
    ids = {case.id for case in CASES}
    for version, table in ANSWERS.items():
        assert set(table) == ids, f"version {version} is missing cases"


def test_a_version_with_no_answer_table_scores_zero():
    unknown = PromptVersion(number=99, text="p")
    assert scripted_runner(unknown, build_task().holdout) == {
        case.id: "" for case in build_task().holdout
    }


# --- Demo ---------------------------------------------------------------


def test_the_demo_shows_all_three_outcomes():
    decisions = [it.decision for it in demo.run(settings()).iterations[1:]]
    assert set(decisions) == {
        Decision.ACCEPTED,
        Decision.REJECTED_NO_GAIN,
        Decision.REJECTED_REGRESSION,
    }


def test_the_demo_improves_the_holdout():
    assert demo.run(settings()).improvement > 0


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "prompt-optimizer demo" in output
    assert "holdout" in output


def test_the_fixture_task_has_both_splits():
    task = build_task()
    assert len(task.tuning) >= 8
    assert len(task.holdout) >= 4
    assert all(isinstance(case, TaskCase) for case in task.cases)


def test_critiques_describe_patterns_not_individual_cases():
    # A critique naming specific cases is how a prompt ends up memorising them.
    from agents.prompt_optimizer.scripted import CRITIQUES

    joined = " ".join(p for critique in CRITIQUES for p in critique.patterns)
    for case in build_task().tuning:
        assert case.id not in joined


def test_a_critique_model_round_trips():
    critique = Critique(patterns=["a"], suggestions=["b"], verdict="c")
    assert Critique.model_validate_json(critique.model_dump_json()) == critique
