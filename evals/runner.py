"""Running the eval suite.

    python -m evals            # the LOGIC layer, free and deterministic
    python -m evals --layer judgement   # needs a live API key

A case that raises is scored zero and reported, not allowed to stop the run.
An eval suite that halts on the first broken case tells you about one problem;
one that finishes tells you about all of them.
"""

from __future__ import annotations

import argparse

from evals.models import CaseResult, EvalCase, EvalReport, Layer, Score, SuiteResult
from evals.registry import CaseFn, load_all


def run_case(case: EvalCase, fn: CaseFn) -> CaseResult:
    """Run one case, converting a crash into a zero rather than a stack trace."""
    try:
        return CaseResult(case=case, score=fn())
    except Exception as exc:  # noqa: BLE001 - cases are arbitrary code
        failure = f"{type(exc).__name__}: {exc}"
        return CaseResult(case=case, score=Score.miss(failure), error=failure)


def run(layer: Layer = Layer.LOGIC) -> EvalReport:
    """Run every case in one layer, grouped by agent."""
    by_agent: dict[str, list[CaseResult]] = {}

    for case, fn in load_all():
        if case.layer is not layer:
            continue
        by_agent.setdefault(case.agent, []).append(run_case(case, fn))

    return EvalReport(
        layer=layer,
        suites=[
            SuiteResult(agent=agent, results=results) for agent, results in sorted(by_agent.items())
        ],
    )


def render_table(report: EvalReport) -> str:
    """The results as a Markdown table, for pasting into a README."""
    lines = [
        "| Agent | Cases | Passed | Score | Known gaps |",
        "|---|---|---|---|---|",
    ]
    for suite in report.suites:
        lines.append(
            f"| {suite.agent} | {len(suite.scored)} | {suite.passed} | "
            f"{suite.score:.0%} | {len(suite.gaps)} |"
        )
    lines.append(
        f"| **overall** | **{sum(len(s.scored) for s in report.suites)}** | "
        f"**{sum(s.passed for s in report.suites)}** | **{report.score:.0%}** | "
        f"**{sum(len(s.gaps) for s in report.suites)}** |"
    )
    return "\n".join(lines)


def _print(report: EvalReport) -> None:
    print(f"\n{'=' * 78}")
    print(f"Eval suite — {report.layer.value} layer")
    print("=" * 78)

    for suite in report.suites:
        print(f"\n{suite.agent}  {suite.score:.0%}  ({suite.passed}/{len(suite.scored)} passed)")
        for result in suite.results:
            if result.case.is_known_gap:
                mark = "gap " if result.value < 1.0 else "FIXED"
            else:
                mark = " ok " if result.value >= 1.0 else "FAIL"
            print(f"  [{mark}] {result.case.id}")
            if result.value < 1.0 and not result.case.is_known_gap:
                print(f"         {result.score.detail}")

    print(f"\n{'=' * 78}")
    print(render_table(report))

    gaps = [r for s in report.suites for r in s.gaps]
    if gaps:
        print(f"\n{len(gaps)} known gaps, kept on purpose:")
        for result in gaps:
            print(f"  - {result.case.id}: {result.case.note or result.case.description}")

    if report.surprises:
        print(f"\n{len(report.surprises)} case(s) did not behave as declared:")
        for result in report.surprises:
            reason = (
                "a known gap unexpectedly passed — update the case"
                if result.case.is_known_gap
                else result.score.detail
            )
            print(f"  ! {result.case.id}: {reason}")


def main() -> int:
    from core.console import configure_stdout

    configure_stdout()
    parser = argparse.ArgumentParser(description="Run the agent eval suite.")
    parser.add_argument(
        "--layer",
        choices=[layer.value for layer in Layer],
        default=Layer.LOGIC.value,
        help="logic (deterministic, free) or judgement (needs a live API key)",
    )
    args = parser.parse_args()

    report = run(Layer(args.layer))
    _print(report)
    return 0 if report.is_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
