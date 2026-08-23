"""A J.A.R.V.I.S.-style operations dashboard for the agent fleet.

The look and the widget vocabulary are taken from `AndrewKochulab/jarvis-
dashboard` (MIT): the arc reactor, the agent cards, the activity heatmap, the
mission-control nav, the quick capture. The implementation is not — that is
JavaScript inside an Obsidian note, backed by a Node companion server; this is
Python rendering one self-contained page, backed by the console that already
exists here.

`jarvis/README.md` lists what was taken, what was changed, and the two counting
bugs the port found in the original's cost figures.

    python -m jarvis            # the dashboard on 127.0.0.1:8756
    python -m jarvis.demo       # every panel, rendered to the terminal
"""

from __future__ import annotations

from jarvis.diagnostics import Check, Diagnostics, measure
from jarvis.panels import Analytics, Dashboard, FleetMember, SessionRow, build
from jarvis.registry import FLEET, AgentCard, reachable_names

__all__ = [
    "FLEET",
    "AgentCard",
    "Analytics",
    "Check",
    "Dashboard",
    "Diagnostics",
    "FleetMember",
    "SessionRow",
    "build",
    "measure",
    "reachable_names",
]
