"""Tests for the non-negotiable rules.

These are the most important tests in this repository. Everything else protects
the codebase from a model; this protects the codebase from an agent that writes
to it, and specifically from the failure worth designing against — a bad patch
plus a quiet adjustment to whatever would have caught it.

Every rule gets a test that fires it, and the near-misses get one too.
"""

from __future__ import annotations

from datetime import date

from agents.code_reviewer.models import Finding, Patch, Reviewer, Severity
from agents.code_reviewer.safety import (
    MAX_FILES_PER_PATCH,
    MAX_PATCH_CHARS,
    MAX_PATCHES_PER_RUN,
    branch_name,
    check_patch,
    is_protected,
    is_self,
    may_modify,
    normalise,
)

RUN_DATE = date(2026, 3, 6)


def finding(path: str = "core/pricing.py") -> Finding:
    return Finding(
        reviewer=Reviewer.CORRECTNESS,
        path=path,
        severity=Severity.MAJOR,
        title="Something is wrong",
        detail="d",
        suggestion="s",
        anchor="a",
    )


def patch(changes: dict[str, str], *, allowed: list[str] | None = None) -> Patch:
    paths = list(changes)
    return Patch(
        finding=finding(paths[0] if paths else "core/pricing.py"),
        branch="improve/2026-03-06-test",
        allowed_paths=allowed if allowed is not None else paths,
        changes=changes,
    )


# --- Path normalisation -------------------------------------------------


def test_windows_separators_are_folded():
    assert normalise("agents\\code_reviewer\\safety.py") == "agents/code_reviewer/safety.py"


def test_a_leading_dot_slash_is_removed_without_eating_a_dotfile():
    # The bug this test exists for: lstrip("./") strips a *set of characters*,
    # so it turned .github/workflows/ci.yml into github/workflows/ci.yml and
    # the CI rule silently stopped matching.
    assert normalise("./core/agent.py") == "core/agent.py"
    assert normalise(".github/workflows/ci.yml") == ".github/workflows/ci.yml"
    assert normalise("./.github/workflows/ci.yml") == ".github/workflows/ci.yml"


# --- What is protected --------------------------------------------------


def test_ci_configuration_is_protected():
    assert is_protected(".github/workflows/ci.yml")


def test_the_top_level_test_directory_is_protected():
    assert is_protected("tests/test_agent.py")


def test_tests_living_beside_their_agent_are_protected():
    # Agent tests are not under tests/, and they are exactly as protective.
    assert is_protected("agents/email_triage/tests/test_policy.py")


def test_a_test_file_anywhere_is_protected():
    assert is_protected("core/test_something.py")


def test_the_eval_suite_is_protected():
    assert is_protected("evals/cases/supervisor.py")


def test_the_build_and_lint_configuration_is_protected():
    for path in ("Makefile", "pyproject.toml", "uv.lock", ".gitignore"):
        assert is_protected(path), path


def test_architecture_decisions_are_protected():
    # An agent that rewrites the reasoning behind its own constraints is not
    # improving anything.
    assert is_protected("docs/adr/0005-monotonic-supervision.md")


def test_ordinary_source_is_not_protected():
    for path in ("core/agent.py", "agents/supervisor/codex.py", "console/overlay.py"):
        assert not is_protected(path), path


def test_a_filename_merely_containing_test_is_not_protected():
    # "latest.py" and "contest.py" are source, not tests.
    assert not is_protected("core/latest.py")
    assert not is_protected("agents/supervisor/contest.py")


# --- Self-modification --------------------------------------------------


def test_the_improver_cannot_patch_itself():
    assert is_self("agents/code_reviewer/safety.py")
    assert is_self("agents/code_reviewer/pipeline.py")
    assert not may_modify("agents/code_reviewer/models.py")


def test_another_agent_is_not_the_improver():
    assert not is_self("agents/supervisor/codex.py")


# --- The combined check -------------------------------------------------


def test_an_ordinary_patch_passes():
    assert check_patch(patch({"core/pricing.py": "x"})) == []


def test_a_patch_touching_a_test_is_refused():
    violations = check_patch(patch({"tests/test_cost.py": "# relaxed\n"}))
    assert violations
    assert "judges its work" in violations[0]


def test_a_patch_touching_ci_is_refused():
    assert check_patch(patch({".github/workflows/ci.yml": "x"})) != []


def test_a_patch_touching_the_improver_is_refused():
    violations = check_patch(patch({"agents/code_reviewer/safety.py": "x"}))
    assert any("through a person" in violation for violation in violations)


def test_an_empty_patch_is_refused():
    assert check_patch(patch({})) != []


def test_a_patch_larger_than_the_ceiling_is_refused():
    oversized = patch({"core/pricing.py": "x" * (MAX_PATCH_CHARS + 1)})
    assert any("rewrite" in violation for violation in check_patch(oversized))


def test_a_patch_exactly_at_the_ceiling_passes():
    assert check_patch(patch({"core/pricing.py": "x" * MAX_PATCH_CHARS})) == []


def test_a_patch_touching_too_many_files_is_refused():
    changes = {f"core/file{i}.py": "x" for i in range(MAX_FILES_PER_PATCH + 1)}
    assert any("file limit" in violation for violation in check_patch(patch(changes)))


def test_a_patch_wandering_outside_its_finding_is_refused():
    wandering = patch(
        {"core/pricing.py": "x", "core/other.py": "y"},
        allowed=["core/pricing.py"],
    )
    violations = check_patch(wandering)
    assert any("did not name" in violation for violation in violations)


def test_the_run_ceiling_refuses_further_patches():
    violations = check_patch(patch({"core/pricing.py": "x"}), applied_so_far=MAX_PATCHES_PER_RUN)
    assert any("limit" in violation for violation in violations)


def test_every_broken_rule_is_reported_not_just_the_first():
    # Somebody reading a refusal should see everything wrong with it.
    bad = Patch(
        finding=finding("tests/test_cost.py"),
        branch="improve/x",
        allowed_paths=["tests/test_cost.py"],
        changes={
            "tests/test_cost.py": "x" * (MAX_PATCH_CHARS + 1),
            "agents/code_reviewer/safety.py": "y",
            "core/a.py": "z",
            "core/b.py": "w",
        },
    )
    violations = check_patch(bad)
    assert len(violations) >= 4


# --- Branch names -------------------------------------------------------


def test_a_branch_name_is_prefixed_and_dated():
    name = branch_name(RUN_DATE, "Discount treats a percentage as a fraction")
    assert name.startswith("improve/2026-03-06-")


def test_a_branch_name_ends_on_a_word():
    # A branch called ...-as-a-fracti looks careless before anyone reads the
    # diff.
    name = branch_name(RUN_DATE, "Discount treats a percentage as a fraction")
    slug = name.rsplit("-", 1)[-1]
    assert slug in "Discount treats a percentage as a fraction".lower().split()


def test_punctuation_is_stripped_from_a_branch_name():
    name = branch_name(RUN_DATE, "Fix: order_total() -- wrong!")
    assert " " not in name
    assert "(" not in name and "!" not in name


def test_an_unusable_title_still_produces_a_branch():
    assert branch_name(RUN_DATE, "!!!") == "improve/2026-03-06-change"
