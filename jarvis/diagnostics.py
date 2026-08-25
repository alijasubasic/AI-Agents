"""What the repository can say about itself, for free.

The dashboard this borrows from has a "system diagnostics" panel showing CPU,
memory and uptime — numbers about the machine. Those are the wrong numbers
here. The interesting question about an agent fleet is not whether the laptop
is warm; it is **whether the guardrails still hold**.

So this panel answers that instead, from facts already in the repository:

* the deterministic eval suite, actually run
* the codex articles that will fire on every decision
* the guardrails on every agent loop
* how many known gaps are documented rather than hidden

Everything here is free and offline. The eval run takes a couple of seconds,
which is why it happens once when the server starts and not on every refresh —
see `Diagnostics.measure`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from agents.supervisor.codex import ARTICLES
from core.config import Settings
from jarvis.registry import FLEET


class Check(BaseModel):
    """One line of the diagnostics panel."""

    label: str
    value: str
    detail: str = ""
    #: "ok", "hold", "block" or "dim" — the same vocabulary the rest of the
    #: console uses for verdicts, so one palette covers everything.
    tone: str = "ok"


class Diagnostics(BaseModel):
    """The panel's contents, and when they were measured."""

    measured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: False when the eval suite was skipped, which the panel says out loud.
    evals_run: bool = False
    checks: list[Check] = Field(default_factory=list)

    @property
    def worst(self) -> str:
        for tone in ("block", "hold"):
            if any(check.tone == tone for check in self.checks):
                return tone
        return "ok"


def _eval_checks() -> list[Check]:
    """Run the deterministic layer and report it.

    Deliberately catches broadly. A dashboard that will not start because one
    eval case raised is a dashboard that hides the problem instead of showing
    it — the panel says the suite errored, which is the useful outcome.
    """
    from evals.models import Layer
    from evals.runner import run

    try:
        report = run(Layer.LOGIC)
    except Exception as error:  # noqa: BLE001 - reported, not swallowed
        return [
            Check(
                label="Eval suite",
                value="errored",
                detail=f"{type(error).__name__}: {error}"[:120],
                tone="block",
            )
        ]

    gaps = sum(len(suite.gaps) for suite in report.suites)
    surprises = len(report.surprises)

    return [
        Check(
            label="Eval suite",
            value=f"{report.score * 100:.0f}%",
            detail=f"{report.total_cases} cases across {len(report.suites)} agents",
            tone="ok" if report.score >= 1.0 else "hold",
        ),
        Check(
            label="Surprises",
            value=str(surprises),
            detail="cases that did not behave as documented",
            tone="ok" if surprises == 0 else "block",
        ),
        Check(
            label="Known gaps",
            value=str(gaps),
            detail="documented failures, excluded from the score",
            tone="ok",
        ),
    ]


def _static_checks(settings: Settings) -> list[Check]:
    """Facts that need no measurement, only reading."""
    reachable = sum(1 for card in FLEET if card.reachable)
    return [
        Check(
            label="Codex articles",
            value=str(len(ARTICLES)),
            detail="applied to every decision, before it leaves",
        ),
        Check(
            label="Agents",
            value=str(len(FLEET)),
            detail=f"{reachable} reachable from the chat box",
        ),
        Check(
            label="Step ceiling",
            value=str(settings.max_steps),
            detail="hard stop on any agent loop",
        ),
        Check(
            label="Run deadline",
            value=f"{settings.timeout_seconds:.0f}s",
            detail="wall clock, not step count",
        ),
        Check(
            label="Cost budget",
            value=f"${settings.max_cost_usd:.2f}",
            detail="per run, checked between steps",
        ),
        Check(
            label="Mode",
            value=settings.mode,
            detail=settings.model if settings.is_live else "scripted providers, no network",
            tone="hold" if settings.is_live else "ok",
        ),
    ]


def measure(settings: Settings | None = None, *, run_evals: bool = True) -> Diagnostics:
    """Take the readings.

    `run_evals=False` skips the expensive part and says so on the panel rather
    than reporting a stale or invented score.
    """
    settings = settings or Settings.from_env()
    checks = _static_checks(settings)

    if run_evals:
        checks = _eval_checks() + checks
    else:
        checks = [
            Check(label="Eval suite", value="not run", detail="skipped on this start", tone="dim"),
            *checks,
        ]

    return Diagnostics(evals_run=run_evals, checks=checks)
