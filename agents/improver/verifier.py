"""The gate a patch has to pass.

Six checks, all of which must pass. The order matters: the cheap deterministic
ones run first, so a patch that was never allowed does not cost a test run.

    SAFETY            may this patch exist at all
    SCOPE             did it touch only what the finding named
    REGRESSION_TEST   is there a test that fails without it
    LINT              make lint
    TESTS             make test
    EVALS             eval score not lower than before

The eval gate is the one worth explaining. `make test` answers "does the code
still work"; it says nothing about whether the agents still *behave* well,
because most of that behaviour is not a unit test. The eval score is, and a
patch that improves a function while lowering the eval score has made the
repository worse in a way tests cannot see.

Nothing here consults a model. A verifier a model could argue with is not a
verifier.
"""

from __future__ import annotations

from agents.improver.models import Gate, GateResult, Patch, Verification
from agents.improver.safety import check_patch, normalise
from agents.improver.workspace import Workspace

LINT_COMMAND = "make lint"
TEST_COMMAND = "make test"
EVAL_COMMAND = "make eval"

#: Findings in these categories are bug fixes and need a regression test.
#: Everything else — naming, a missing docstring, a clearer error message —
#: does not, and demanding one would produce tests that assert nothing.
BUG_SEVERITIES = ("blocker", "major")


def _gate(gate: Gate, passed: bool, detail: str = "") -> GateResult:
    return GateResult(gate=gate, passed=passed, detail=detail)


def check_safety(patch: Patch, *, applied_so_far: int) -> GateResult:
    violations = check_patch(patch, applied_so_far=applied_so_far)
    return _gate(
        Gate.SAFETY,
        not violations,
        "; ".join(violations) or "no rule broken",
    )


def check_scope(patch: Patch) -> GateResult:
    """Only the files the finding named may change.

    Separate from the safety check even though both look at paths. Safety asks
    "is this file off limits to the improver at all"; scope asks "did this
    patch wander outside the change it was supposed to make". A patch that
    fixes its finding and tidies three other files on the way is refused, not
    because the tidying is wrong but because nobody reviewed it.
    """
    allowed = {normalise(path) for path in patch.allowed_paths}
    touched = {normalise(path) for path in patch.touched}
    outside = sorted(touched - allowed) if allowed else []

    return _gate(
        Gate.SCOPE,
        not outside,
        f"touched {', '.join(outside)} outside the finding" if outside else "in scope",
    )


def check_regression_test(patch: Patch) -> GateResult:
    """A bug fix ships with a test that fails without it.

    The improver cannot write into `tests/`, so it cannot add the test itself.
    What it can do is produce one for a person to add, and that is what this
    gate requires: no test, no bug fix.
    """
    needs_test = patch.finding.severity.label in BUG_SEVERITIES
    if not needs_test:
        return _gate(Gate.REGRESSION_TEST, True, "not a bug fix; no test required")

    has_test = bool(patch.regression_test.strip())
    return _gate(
        Gate.REGRESSION_TEST,
        has_test,
        "regression test supplied for review"
        if has_test
        else f"{patch.finding.severity.label} finding with no regression test",
    )


def _command_gate(gate: Gate, workspace: Workspace, command: str) -> GateResult:
    result = workspace.run(command)
    return _gate(
        gate,
        result.passed,
        f"{command} passed" if result.passed else f"{command} failed:\n{result.tail}",
    )


def check_evals(workspace: Workspace, *, baseline_output: str) -> GateResult:
    """The eval suite must not score worse than it did before the patch.

    Compared by exit code and by the reported overall line rather than by
    parsing a number out of prose. `make eval` already exits non-zero when
    anything behaves differently from what its case declared, which is the
    property worth gating on: a patch that silently fixes a documented gap is
    as much a surprise as one that breaks a passing case.
    """
    result = workspace.run(EVAL_COMMAND)
    if not result.passed:
        return _gate(Gate.EVALS, False, f"eval suite failed:\n{result.tail}")

    before = _overall_line(baseline_output)
    after = _overall_line(result.output)
    if before and after and before != after:
        return _gate(
            Gate.EVALS, False, f"eval score changed\n  before: {before}\n  after:  {after}"
        )

    return _gate(Gate.EVALS, True, after or "eval suite passed")


def _overall_line(output: str) -> str:
    for line in output.splitlines():
        if "**overall**" in line:
            return line.strip()
    return ""


def verify(
    patch: Patch,
    workspace: Workspace,
    *,
    applied_so_far: int = 0,
    baseline_eval_output: str = "",
) -> Verification:
    """Run every gate, cheapest first, stopping at the first failure.

    Stopping early is right here even though other parts of this repository
    accumulate reasons: the later gates run a full test suite, and running it
    to add detail to a patch that was already refused wastes minutes for
    nothing.
    """
    checks = [
        lambda: check_safety(patch, applied_so_far=applied_so_far),
        lambda: check_scope(patch),
        lambda: check_regression_test(patch),
        lambda: _command_gate(Gate.LINT, workspace, LINT_COMMAND),
        lambda: _command_gate(Gate.TESTS, workspace, TEST_COMMAND),
        lambda: check_evals(workspace, baseline_output=baseline_eval_output),
    ]

    results: list[GateResult] = []
    for check in checks:
        result = check()
        results.append(result)
        if not result.passed:
            break

    return Verification(results=results)
