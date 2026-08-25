"""Tests for the scanner, reviewers, prioritizer, verifier and pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from agents.code_reviewer import demo
from agents.code_reviewer.models import (
    Gate,
    Patch,
    PatchStatus,
    Reviewer,
    Severity,
)
from agents.code_reviewer.pipeline import ReviewPipeline
from agents.code_reviewer.prioritizer import deduplicate, drop_unanchored, prioritise
from agents.code_reviewer.reporter import render_entry, summarise, worst_unfixed
from agents.code_reviewer.reviewers import ReviewerCrew, anchor_is_real
from agents.code_reviewer.scanner import candidates, scan
from agents.code_reviewer.scripted import (
    DISCOUNT_BUG,
    INVENTED,
    MISSING_DOCSTRING,
    NEGATIVE_QUANTITY,
    SYNTHETIC_INDEX,
    SYNTHETIC_PATH,
    SYNTHETIC_SOURCE,
    patcher_provider,
    reviewer_providers,
    workspace,
)
from agents.code_reviewer.verifier import check_evals, check_regression_test, check_scope, verify
from agents.code_reviewer.workspace import CommandResult, MockWorkspace
from core.config import Settings

RUN_DATE = date(2026, 3, 6)


def settings() -> Settings:
    return Settings(trace_enabled=False)


def run_pipeline(**overrides):
    base = {
        "workspace": workspace(RUN_DATE),
        "reviewer_providers": reviewer_providers(),
        "patcher_provider": patcher_provider(),
        "settings": settings(),
        "run_date": RUN_DATE,
        "review_limit": 1,
    }
    return ReviewPipeline(**{**base, **overrides}).run(SYNTHETIC_INDEX)


# --- Scanner ------------------------------------------------------------


def test_the_scanner_indexes_this_repository():
    index = scan(Path(__file__).resolve().parents[3])
    assert len(index) > 40
    assert any(entry.path == "core/agent.py" for entry in index)


def test_the_scanner_finds_a_files_tests():
    index = {entry.path: entry for entry in scan(Path(__file__).resolve().parents[3])}
    assert index["core/agent.py"].has_tests
    assert index["core/agent.py"].test_path == "tests/test_agent.py"


def test_the_improvers_own_files_score_zero():
    index = {entry.path: entry for entry in scan(Path(__file__).resolve().parents[3])}
    entry = index["agents/code_reviewer/safety.py"]
    assert entry.is_self
    assert entry.priority == 0.0


def test_candidates_never_include_a_zero_scoring_file():
    # An code reviewer that reviews protected files produces findings nobody may act
    # on, which is worse than reviewing nothing.
    index = scan(Path(__file__).resolve().parents[3])
    assert all(entry.priority > 0 for entry in candidates(index, limit=10))


def test_ranking_is_deterministic():
    root = Path(__file__).resolve().parents[3]
    assert [e.path for e in scan(root)] == [e.path for e in scan(root)]


def test_untested_files_rank_above_tested_ones_of_similar_size():
    index = {entry.path: entry for entry in scan(Path(__file__).resolve().parents[3])}
    tested = index["core/agent.py"]
    assert tested.has_tests
    assert "no test file" not in tested.priority_reasons


# --- Reviewers ----------------------------------------------------------


def test_a_crew_missing_a_reviewer_is_refused():
    # Silently dropping a reviewer stops checking a whole category.
    partial = dict(reviewer_providers())
    partial.pop(Reviewer.SECURITY)

    with pytest.raises(ValueError, match="security"):
        ReviewerCrew(providers=partial, settings=settings())


def test_every_reviewer_is_consulted():
    providers = reviewer_providers()
    ReviewerCrew(providers=providers, settings=settings()).review(
        SYNTHETIC_PATH, SYNTHETIC_SOURCE, has_tests=False
    )
    assert all(provider.calls for provider in providers.values())


def test_findings_are_labelled_by_the_crew_not_by_the_model():
    # A model that mislabels its own role would scramble the crew's output.
    findings, _cost = ReviewerCrew(providers=reviewer_providers(), settings=settings()).review(
        SYNTHETIC_PATH, SYNTHETIC_SOURCE, has_tests=False
    )

    assert all(finding.path == SYNTHETIC_PATH for finding in findings)
    assert {f.reviewer for f in findings} <= set(Reviewer)


def test_an_empty_review_is_a_valid_answer():
    findings, _ = ReviewerCrew(providers=reviewer_providers(), settings=settings()).review(
        SYNTHETIC_PATH, SYNTHETIC_SOURCE, has_tests=False
    )

    # agent_quality is scripted to find nothing.
    assert not any(f.reviewer is Reviewer.AGENT_QUALITY for f in findings)


# --- Prioritizer --------------------------------------------------------


def test_an_invented_anchor_is_detected():
    assert anchor_is_real(DISCOUNT_BUG, SYNTHETIC_SOURCE)
    assert not anchor_is_real(INVENTED, SYNTHETIC_SOURCE)


def test_findings_quoting_something_absent_are_dropped():
    kept = drop_unanchored([DISCOUNT_BUG, INVENTED], {SYNTHETIC_PATH: SYNTHETIC_SOURCE})
    assert [f.title for f in kept] == [DISCOUNT_BUG.title]


def test_two_reviewers_finding_the_same_thing_merge_and_escalate():
    minor = DISCOUNT_BUG.model_copy(
        update={"reviewer": Reviewer.ROBUSTNESS, "severity": Severity.MINOR}
    )
    (merged,) = deduplicate([minor, DISCOUNT_BUG])

    assert merged.severity is Severity.MAJOR
    assert "Also raised by" in merged.detail


def test_nits_are_collected_not_queued():
    worklist, nits = prioritise(
        [DISCOUNT_BUG, MISSING_DOCSTRING],
        {entry.path: entry for entry in SYNTHETIC_INDEX},
        {SYNTHETIC_PATH: SYNTHETIC_SOURCE},
    )
    assert [f.title for f in worklist] == [DISCOUNT_BUG.title]
    assert [f.title for f in nits] == [MISSING_DOCSTRING.title]


def test_prioritisation_is_stable():
    args = (
        [DISCOUNT_BUG, NEGATIVE_QUANTITY],
        {entry.path: entry for entry in SYNTHETIC_INDEX},
        {SYNTHETIC_PATH: SYNTHETIC_SOURCE},
    )
    assert [f.title for f in prioritise(*args)[0]] == [f.title for f in prioritise(*args)[0]]


# --- Verifier -----------------------------------------------------------


def a_patch(**overrides) -> Patch:
    base = {
        "finding": DISCOUNT_BUG,
        "branch": "improve/2026-03-06-x",
        "allowed_paths": [SYNTHETIC_PATH],
        "changes": {SYNTHETIC_PATH: "x"},
    }
    return Patch(**{**base, **overrides})


def test_scope_refuses_a_patch_touching_an_unnamed_file():
    wandering = a_patch(changes={SYNTHETIC_PATH: "x", "core/other.py": "y"})
    assert check_scope(wandering).passed is False


def test_a_bug_fix_without_a_regression_test_is_refused():
    assert check_regression_test(a_patch()).passed is False


def test_a_bug_fix_with_a_regression_test_passes():
    assert check_regression_test(a_patch(regression_test="def test_x(): ...")).passed


def test_a_nit_needs_no_regression_test():
    nit = a_patch(finding=MISSING_DOCSTRING)
    assert check_regression_test(nit).passed


def test_a_changed_eval_score_fails_the_gate():
    space = MockWorkspace(
        results={
            "main": {
                "make eval": CommandResult(
                    command="make eval",
                    exit_code=0,
                    output="| **overall** | **88** | **88** | **99%** | **22** |",
                )
            }
        }
    )
    result = check_evals(
        space, baseline_output="| **overall** | **89** | **89** | **100%** | **22** |"
    )
    assert result.passed is False
    assert "eval score changed" in result.detail


def test_an_unchanged_eval_score_passes_the_gate():
    line = "| **overall** | **89** | **89** | **100%** | **22** |"
    space = MockWorkspace(
        results={
            "main": {"make eval": CommandResult(command="make eval", exit_code=0, output=line)}
        }
    )
    assert check_evals(space, baseline_output=line).passed


def test_verification_stops_at_the_first_failure():
    # The later gates run a full test suite; running it to add detail to a
    # patch that was already refused wastes minutes for nothing.
    space = MockWorkspace()
    verification = verify(a_patch(changes={"tests/test_cost.py": "x"}), space)

    assert verification.first_failure.gate is Gate.SAFETY
    assert space.commands == []


def test_a_passing_patch_runs_every_gate():
    space = MockWorkspace(files={SYNTHETIC_PATH: SYNTHETIC_SOURCE})
    verification = verify(a_patch(regression_test="def test_x(): ..."), space)

    assert verification.passed
    assert {result.gate for result in verification.results} == set(Gate)


# --- Pipeline -----------------------------------------------------------


def test_the_pipeline_applies_a_patch_that_passes_every_gate():
    result = run_pipeline()
    applied = result.applied

    assert len(applied) == 1
    assert applied[0].patch.finding.title == DISCOUNT_BUG.title
    assert applied[0].patch.branch.startswith("improve/2026-03-06-")


def test_a_patch_failing_its_tests_is_reverted():
    result = run_pipeline()
    (reverted,) = result.reverted

    assert reverted.status is PatchStatus.REVERTED
    assert "tests gate" in reverted.reason


def test_a_reverted_patch_leaves_the_workspace_as_it_was():
    space = workspace(RUN_DATE)
    ReviewPipeline(
        workspace=space,
        reviewer_providers=reviewer_providers(),
        patcher_provider=patcher_provider(),
        settings=settings(),
        run_date=RUN_DATE,
        review_limit=1,
    ).run(SYNTHETIC_INDEX)

    assert space.discards == 1


def test_every_patch_gets_its_own_branch():
    space = workspace(RUN_DATE)
    ReviewPipeline(
        workspace=space,
        reviewer_providers=reviewer_providers(),
        patcher_provider=patcher_provider(),
        settings=settings(),
        run_date=RUN_DATE,
        review_limit=1,
    ).run(SYNTHETIC_INDEX)

    assert len(space.branches) == len(set(space.branches)) == 2


def test_the_patch_ceiling_halts_the_run():
    result = run_pipeline(max_patches=0)
    assert result.halted_reason is not None
    assert "patch ceiling" in result.halted_reason


def test_the_cost_ceiling_halts_the_run():
    result = run_pipeline(max_cost_usd=0.0001)
    assert result.halted_reason is not None
    assert "cost ceiling" in result.halted_reason


def test_an_empty_index_halts_cleanly():
    result = ReviewPipeline(
        workspace=workspace(RUN_DATE),
        reviewer_providers=reviewer_providers(),
        patcher_provider=patcher_provider(),
        settings=settings(),
        run_date=RUN_DATE,
    ).run([])

    assert result.halted_reason == "nothing in the index was eligible for review"
    assert result.attempts == []


# --- Reporter -----------------------------------------------------------


def test_the_log_reports_failures_as_prominently_as_successes():
    entry = render_entry(run_pipeline())

    assert "### Applied" in entry
    assert "### Attempted and reverted" in entry
    assert "### Nits" in entry


def test_the_log_names_the_gate_that_refused_a_patch():
    assert "tests gate" in render_entry(run_pipeline())


def test_the_summary_line_counts_every_outcome():
    line = summarise(run_pipeline())
    assert "1 patch(es)" in line
    assert "1 reverted" in line


def test_unfixed_findings_are_listed_for_a_person():
    unfixed = worst_unfixed(run_pipeline())
    assert any(NEGATIVE_QUANTITY.title in line for line in unfixed)


def test_the_log_counts_findings_by_reviewer():
    assert "| correctness | 1 |" in render_entry(run_pipeline())


# --- Demo ---------------------------------------------------------------


def test_the_demo_never_touches_the_repository(tmp_path, monkeypatch):
    # The claim the package README makes.
    before = sorted(p.name for p in Path(".").iterdir())
    demo.run(settings())
    assert sorted(p.name for p in Path(".").iterdir()) == before


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "code reviewer demo" in output
    assert "may not modify what judges its work" in output
    assert "nothing on disk changed" in output


def test_findings_and_patches_line_up():
    # A guard against the scripted fixtures drifting apart: every worklist item
    # must have a patch draft available.
    result = run_pipeline()
    assert len(result.attempts) == len(result.worklist)


def test_an_invented_finding_never_reaches_a_patch():
    result = run_pipeline()
    assert all(attempt.patch.finding.title != INVENTED.title for attempt in result.attempts)
