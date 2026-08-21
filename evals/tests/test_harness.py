"""Tests for the eval harness itself.

An eval suite that miscounts is worse than no eval suite: it produces a number
people trust. These tests cover the scoring arithmetic and the bookkeeping, not
the agents.
"""

from __future__ import annotations

import pytest

from evals.models import (
    CaseResult,
    EvalCase,
    EvalReport,
    Expectation,
    Layer,
    Score,
    SuiteResult,
)
from evals.registry import REGISTRY, case, clear, load_all
from evals.runner import render_table, run, run_case
from evals.scoring import (
    at_least,
    combine,
    contains_all,
    equals,
    excludes_all,
    set_equals,
    within,
)


def a_case(**overrides) -> EvalCase:
    base = {
        "id": "c1",
        "agent": "test-agent",
        "layer": Layer.LOGIC,
        "description": "A case.",
    }
    return EvalCase(**{**base, **overrides})


def result(value: float, **overrides) -> CaseResult:
    return CaseResult(case=a_case(**overrides), score=Score(value=value))


# --- Scorers ------------------------------------------------------------


def test_an_exact_match_scores_full_marks():
    assert equals(3, 3).value == 1.0
    assert equals(3, 4).value == 0.0


def test_contains_all_gives_partial_credit():
    score = contains_all("alpha beta", ["alpha", "beta", "gamma"])
    assert score.value == pytest.approx(2 / 3)
    assert "gamma" in score.detail


def test_contains_all_is_case_insensitive():
    assert contains_all("ALPHA", ["alpha"]).value == 1.0


def test_excludes_all_is_all_or_nothing():
    # "Mostly did not leak the phone number" is not a partial success.
    assert excludes_all("clean text", ["secret"]).value == 1.0
    assert excludes_all("contains a secret", ["secret", "other"]).value == 0.0


def test_set_equality_scores_by_overlap():
    score = set_equals({"a", "b"}, {"a", "b", "c"})
    assert score.value == pytest.approx(2 / 3)
    assert "missing" in score.detail


def test_an_extra_element_is_penalised_too():
    assert set_equals({"a", "b", "c"}, {"a", "b"}).value < 1.0


def test_numeric_tolerance():
    assert within(0.286, 2 / 7, tolerance=0.01).value == 1.0
    assert within(0.5, 2 / 7, tolerance=0.01).value == 0.0


def test_at_least_is_inclusive():
    assert at_least(3, 3).value == 1.0
    assert at_least(2.9, 3).value == 0.0


def test_combining_scores_averages_them():
    assert combine(Score.hit(), Score.miss("no")).value == 0.5


def test_combining_keeps_only_the_failures_in_the_detail():
    detail = combine(Score.hit("fine"), Score.miss("broken")).detail
    assert "broken" in detail
    assert "fine" not in detail


def test_combining_nothing_is_a_pass():
    assert combine().value == 1.0


# --- Bookkeeping --------------------------------------------------------


def test_known_gaps_are_excluded_from_the_score():
    # Letting a documented limitation drag the number down creates pressure to
    # delete the case, which is the opposite of what it is for.
    suite = SuiteResult(
        agent="a",
        results=[
            result(1.0, id="good"),
            result(0.0, id="gap", expectation=Expectation.KNOWN_GAP),
        ],
    )
    assert suite.score == 1.0
    assert len(suite.scored) == 1
    assert len(suite.gaps) == 1


def test_a_failing_gap_is_behaving_as_declared():
    assert result(0.0, expectation=Expectation.KNOWN_GAP).as_expected is True


def test_a_passing_gap_is_a_surprise():
    # Someone fixed it and forgot the case. That is news, not a silent win.
    assert result(1.0, expectation=Expectation.KNOWN_GAP).as_expected is False


def test_a_failing_ordinary_case_is_a_surprise():
    assert result(0.0).as_expected is False


def test_a_suite_with_no_scored_cases_is_clean():
    suite = SuiteResult(agent="a", results=[result(0.0, expectation=Expectation.KNOWN_GAP)])
    assert suite.score == 1.0
    assert suite.is_clean


def test_the_report_weights_agents_equally_not_cases():
    # An agent with forty cases must not drown out one with ten; otherwise the
    # number tracks test-writing effort rather than quality.
    big = SuiteResult(agent="big", results=[result(1.0, id=f"b{i}") for i in range(40)])
    small = SuiteResult(agent="small", results=[result(0.0, id="s1")])
    report = EvalReport(layer=Layer.LOGIC, suites=[big, small])

    assert report.score == 0.5


def test_an_empty_report_scores_one():
    assert EvalReport(layer=Layer.LOGIC).score == 1.0


def test_surprises_surface_from_every_suite():
    report = EvalReport(
        layer=Layer.LOGIC,
        suites=[
            SuiteResult(agent="a", results=[result(0.0, id="a1")]),
            SuiteResult(agent="b", results=[result(1.0, id="b1")]),
        ],
    )
    assert [r.case.id for r in report.surprises] == ["a1"]
    assert report.is_clean is False


# --- Runner -------------------------------------------------------------


def test_a_crashing_case_scores_zero_rather_than_stopping_the_run():
    def explode() -> Score:
        raise RuntimeError("boom")

    outcome = run_case(a_case(), explode)

    assert outcome.value == 0.0
    assert "boom" in (outcome.error or "")


def test_the_registry_rejects_duplicate_ids():
    clear()
    try:

        @case(id="dup", agent="a", layer=Layer.LOGIC, description="x")
        def _first() -> Score:
            return Score.hit()

        with pytest.raises(ValueError, match="Duplicate"):

            @case(id="dup", agent="a", layer=Layer.LOGIC, description="x")
            def _second() -> Score:
                return Score.hit()

    finally:
        clear()
        load_all()


def test_running_a_layer_only_includes_that_layer():
    report = run(Layer.JUDGEMENT)
    assert all(r.case.layer is Layer.JUDGEMENT for s in report.suites for r in s.results)


def test_the_table_renders_every_suite_and_a_total():
    table = render_table(
        EvalReport(
            layer=Layer.LOGIC,
            suites=[SuiteResult(agent="alpha", results=[result(1.0)])],
        )
    )
    assert "| alpha |" in table
    assert "**overall**" in table


# --- The real suite -----------------------------------------------------


def test_every_registered_case_has_a_unique_id():
    ids = [registered.id for registered, _ in load_all()]
    assert len(ids) == len(set(ids))


def test_every_known_gap_explains_itself():
    # A gap without a note is just a failing test nobody understands.
    for registered, _ in load_all():
        if registered.is_known_gap:
            assert registered.note, f"{registered.id} has no note"


def test_the_logic_layer_behaves_exactly_as_declared():
    # The suite that runs in CI. Any surprise here is a real regression or a
    # case whose documentation has gone stale.
    report = run(Layer.LOGIC)
    assert report.is_clean, [r.case.id for r in report.surprises]


def test_the_logic_layer_covers_every_finished_agent():
    """No agent ships without eval cases.

    The agent list is discovered from the filesystem rather than written out
    here. A hardcoded list is the kind of thing that quietly stops matching
    reality, and then the test that was supposed to catch a missing suite is
    the thing that needs updating instead.
    """
    from pathlib import Path

    agents_dir = Path(__file__).resolve().parents[2] / "agents"
    shipped = {
        package.name.replace("_", "-")
        for package in agents_dir.iterdir()
        if package.is_dir() and (package / "demo.py").exists()
    }
    covered = {suite.agent for suite in run(Layer.LOGIC).suites}

    assert shipped, "no agent packages found; the discovery path is wrong"
    assert shipped - covered == set(), f"agents without eval cases: {shipped - covered}"


def test_the_suite_is_registered_once_however_often_it_is_loaded():
    before = len(load_all())
    load_all()
    assert len(REGISTRY) == before
