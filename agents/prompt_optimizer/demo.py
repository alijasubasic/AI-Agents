"""Runnable demonstration of the evaluator-optimizer loop.

    python -m agents.prompt_optimizer.demo

Improves a routing prompt over three iterations. One version is accepted, one
is rejected for learning its examples, and one is rolled back as a regression.
No API key, no network.
"""

from __future__ import annotations

from agents.prompt_optimizer.fixtures import build_task
from agents.prompt_optimizer.loop import OptimizerLoop
from agents.prompt_optimizer.models import Decision, OptimizerRun
from agents.prompt_optimizer.scripted import (
    critic_provider,
    optimizer_provider,
    scripted_runner,
)
from core.config import Settings
from core.console import configure_stdout

_MARK = {
    None: "baseline",
    Decision.ACCEPTED: "ACCEPTED",
    Decision.REJECTED_NO_GAIN: "rejected",
    Decision.REJECTED_REGRESSION: "rejected",
}


def run(settings: Settings | None = None) -> OptimizerRun:
    """Run the loop against the fixture task."""
    return OptimizerLoop(
        task=build_task(),
        runner=scripted_runner,
        critic_provider=critic_provider(),
        optimizer_provider=optimizer_provider(),
        settings=settings or Settings.from_env(),
        max_iterations=3,
    ).run()


def _print(result: OptimizerRun) -> None:
    print(f"\n{'=' * 78}")
    print(f"{'version':<9} {'tuning':>8} {'holdout':>9} {'gap':>7}   outcome")
    print("=" * 78)

    for iteration in result.iterations:
        print(
            f"{iteration.version.label:<9} "
            f"{iteration.tuning.score:>7.0%} "
            f"{iteration.holdout.score:>8.0%} "
            f"{iteration.overfit_gap:>+7.0%}   "
            f"{_MARK[iteration.decision]}"
        )
        if iteration.reason:
            print(f"          {iteration.reason}")

    best = result.best
    print(f"\n{'=' * 78}")
    print(
        f"{len(result.iterations) - 1} proposals | {result.accepted_count} accepted | "
        f"holdout {result.improvement:+.0%} | ${result.total_cost_usd:.4f}"
    )
    if best is not None:
        print(f"\nBest version: {best.version.label} at {best.holdout.score:.0%} on holdout")
        for line in best.version.text.strip().splitlines():
            print(f"  {line}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    task = build_task()

    print("prompt-optimizer demo")
    print(
        f"mode={settings.mode}  model={settings.model}  task={task.name}  "
        f"{len(task.tuning)} tuning / {len(task.holdout)} holdout cases"
    )

    result = run(settings)
    _print(result)

    overfit = [it for it in result.iterations if it.decision is Decision.REJECTED_NO_GAIN]
    print(f"\n{'=' * 78}")
    if overfit:
        worst = max(overfit, key=lambda it: it.overfit_gap)
        print(
            f"{worst.version.label} scored {worst.tuning.score:.0%} on the cases it was\n"
            f"shown and {worst.holdout.score:.0%} on the ones it was not. Without a holdout\n"
            f"split it would have looked like the best version of the run."
        )
    print(
        "\nAcceptance is decided on the holdout alone, which neither the critic\n"
        "nor the optimizer ever sees. A rejected version is rolled back rather\n"
        "than built on."
    )


if __name__ == "__main__":
    main()
