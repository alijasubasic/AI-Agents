"""Runnable demonstration of the telemetry scan.

    python -m telemetry.demo

Reads this machine's own Claude Code history if there is any, and says plainly
which of the two it found. No API key, no network, no cost — the data is
already on the disk.
"""

from __future__ import annotations

from datetime import datetime

from core.console import configure_stdout
from telemetry import load
from telemetry.models import Telemetry

_BLOCKS = " ▁▂▃▄▅▆▇█"


def _spark(values: list[int], width: int = 24) -> str:
    """A one-line bar chart. Enough to see a shape in a terminal."""
    if not values or not any(values):
        return "no activity"
    trimmed = values[-width:]
    peak = max(trimmed)
    return "".join(_BLOCKS[min(8, round(value / peak * 8))] for value in trimmed)


def _heat(telemetry: Telemetry) -> str:
    return _spark([day.messages for day in telemetry.days], width=telemetry.window_days)


def show(telemetry: Telemetry) -> None:
    print("=" * 78)
    print("Claude Code telemetry")
    print("=" * 78)
    label = "real scan" if telemetry.real else "FIXTURES — nothing real was found"
    print(f"  source:   {telemetry.source}")
    print(f"  data:     {label}")
    print(f"  window:   last {telemetry.window_days} days")

    print(f"\n{'-' * 78}\n  Totals\n{'-' * 78}")
    print(f"  sessions:    {telemetry.sessions:>10,}")
    print(f"  messages:    {telemetry.messages:>10,}")
    print(f"  tool calls:  {telemetry.tool_calls:>10,}")
    print(f"  tokens:      {telemetry.tokens:>10,}")
    print(f"  cost:        {f'${telemetry.cost_usd:.2f}':>10}")
    print(f"  per session: {f'${telemetry.cost_per_session:.2f}':>10}")

    print(f"\n{'-' * 78}\n  Daily messages ({telemetry.window_days}d)\n{'-' * 78}")
    print(f"  {_heat(telemetry)}")
    busiest = telemetry.busiest_hour
    if busiest is not None:
        print(f"  busiest hour of the day: {busiest:02d}:00")
        print(f"  {_spark(telemetry.hourly, width=24)}   (00h -> 23h)")

    print(f"\n{'-' * 78}\n  Models\n{'-' * 78}")
    for share in telemetry.models:
        bar = "#" * max(1, share.percent // 4)
        print(
            f"  {share.family:<9} {share.percent:>3}%  {bar:<25} "
            f"{share.sessions:>4} {'session' if share.sessions == 1 else 'sessions'}  "
            f"${share.cost_usd:.2f}"
        )
    if not telemetry.models:
        print("  none")

    print(f"\n{'-' * 78}\n  Live sessions\n{'-' * 78}")
    for session in telemetry.live:
        print(
            f"  [{session.activity.value:<7}] {session.project:<14} "
            f"{session.doing:<28} {session.age_label}"
        )
    if not telemetry.live:
        print("  nothing running")

    print(f"\n{'-' * 78}")
    print("  Nothing above is message text. Counts, timestamps, model ids and")
    print("  tool names only — see the rule at the top of telemetry/models.py.")


def main() -> None:
    configure_stdout()
    started = datetime.now()
    telemetry = load()
    show(telemetry)
    print(f"  scanned in {(datetime.now() - started).total_seconds():.2f}s")


if __name__ == "__main__":
    main()
