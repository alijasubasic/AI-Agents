"""Runnable demonstration of the dashboard, without a browser.

    python -m jarvis.demo

Builds exactly the payload the page renders and prints it as text. No API key,
no network, no server — which is the point: if this prints, the dashboard has
something to draw.
"""

from __future__ import annotations

from console.briefing import build_overlay_state
from console.chat_demo import build_session
from core.config import Settings
from core.console import configure_stdout
from jarvis.diagnostics import measure
from jarvis.panels import Dashboard, build
from jarvis.ui import render_dashboard
from telemetry import load

RULE = "=" * 78
THIN = "-" * 78


def _section(title: str) -> None:
    print(f"\n{THIN}\n  {title}\n{THIN}")


def _fleet(dashboard: Dashboard) -> None:
    _section("Agent fleet — in this process")
    for member in dashboard.fleet:
        flag = "chat" if member.reachable else "fixtures"
        activity = f"{member.tasks} task(s), {member.last}" if member.tasks else "idle"
        print(f"  [{member.initials}] {member.title:<18} {flag:<9} {activity}")


def _sessions(dashboard: Dashboard) -> None:
    _section("Live sessions — Claude Code on this machine")
    for row in dashboard.sessions:
        print(f"  [{row.activity:<7}] {row.project:<14} {row.doing:<34} {row.age}")
    if not dashboard.sessions:
        print("  nothing running")


def _analytics(dashboard: Dashboard) -> None:
    analytics = dashboard.analytics
    if analytics is None:
        return

    label = "real" if analytics.real else "FIXTURES"
    _section(f"Activity — {analytics.window_days} days, {label}")
    print(
        f"  {analytics.sessions} sessions · {analytics.messages:,} messages · "
        f"{analytics.tokens:,} tokens · ${analytics.cost_usd:,.2f}"
    )

    blocks = " ░▒▓█"
    heat = "".join(blocks[min(4, int(cell.level * 4.99))] for cell in analytics.days)
    print(f"\n  daily   {heat}")

    peak = analytics.peak_hourly or 1
    hours = "".join(blocks[min(4, int(count / peak * 4.99))] for count in analytics.hourly)
    print(f"  hourly  {hours}")
    if analytics.busiest_hour is not None:
        print(f"          busiest at {analytics.busiest_hour:02d}:00")

    print()
    for share in analytics.models:
        bar = "#" * max(1, share["percent"] // 4)
        print(f"  {share['family']:<9} {share['percent']:>3}%  {bar:<25} ${share['cost_usd']:.2f}")


def _diagnostics(dashboard: Dashboard) -> None:
    _section("System diagnostics — the guardrails, not the CPU")
    for check in dashboard.checks:
        mark = {"ok": " ok ", "hold": "hold", "block": "STOP", "dim": " -- "}
        print(
            f"  [{mark.get(check['tone'], '    ')}] {check['label']:<17} "
            f"{check['value']:<10} {check['detail']}"
        )


def _conversation(dashboard: Dashboard) -> None:
    _section("Communication link")
    for turn in dashboard.turns:
        text = " ".join(turn["text"].split())
        print(f"  {turn['speaker']:<9} {text[:62]}")
    for question in dashboard.questions:
        print(f"  -> asking  {question['text'][:62]}")


def run(settings: Settings | None = None) -> Dashboard:
    """Build the dashboard from the scripted console and real telemetry."""
    settings = settings or Settings.from_env()

    session = build_session(settings)
    for request in ("Research Kestrel Systems", "What restocking fee applies to opened stock?"):
        session.submit(request)

    from agents.supervisor import demo as supervisor_demo

    return build(
        state=build_overlay_state(
            supervisor_demo.run(settings.model_copy(update={"mode": "mock"}))
        ),
        conversation=session.conversation,
        telemetry=load(),
        diagnostics=measure(settings, run_evals=True),
        mode=settings.mode,
        model=settings.model,
        capture_target="vault",
    )


def main() -> None:
    configure_stdout()
    print(RULE)
    print("J.A.R.V.I.S. — agent operations dashboard")
    print(RULE)
    print("  Running the eval suite for the diagnostics panel, a moment…")

    dashboard = run(Settings.from_env())
    print(f"  {dashboard.subheading}")

    _conversation(dashboard)
    _fleet(dashboard)
    _sessions(dashboard)
    _analytics(dashboard)
    _diagnostics(dashboard)

    page = render_dashboard(dashboard)
    print(f"\n{RULE}")
    print(f"  The page itself is {len(page) // 1024} KB, self-contained, no CDN.")
    print("  python -m jarvis    ->  http://127.0.0.1:8756")


if __name__ == "__main__":
    main()
