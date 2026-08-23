"""Assembling what the dashboard renders.

One function per panel, each returning plain data, composed by `build`. The
page is then a renderer with no opinions — which is the property that makes it
possible to test the dashboard without a browser.

**One join is deliberately not made.** The source dashboard shows agent cards
and live sessions as one fleet, because there its agents *are* Claude Code
subagents and a card lighting up means that subagent is running. Here they are
two different things: the eight agents in `agents/` run in this process when
you type a request, while the live sessions are Claude Code transcripts on this
machine that have nothing to do with them. Wiring one to the other would make
an agent card flicker because you opened a terminal somewhere else.

So there are two panels and they say what they are. The fleet's status comes
from the conversation; the sessions panel comes from telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from console.models import OverlayState
from console.tasks import Conversation, TaskStatus
from jarvis.diagnostics import Diagnostics
from jarvis.registry import FLEET, AgentCard
from telemetry.models import Telemetry

#: Task status -> the tone vocabulary shared with verdicts and diagnostics.
_STATUS_TONE: dict[TaskStatus, str] = {
    TaskStatus.DONE: "ok",
    TaskStatus.ESCALATED: "hold",
    TaskStatus.BLOCKED: "block",
    TaskStatus.FAILED: "block",
    TaskStatus.NEEDS_CLARIFICATION: "hold",
    TaskStatus.UNROUTABLE: "hold",
    TaskStatus.QUEUED: "dim",
}


class FleetMember(BaseModel):
    """An agent card, with whatever this session has asked of it."""

    name: str
    title: str
    initials: str
    colour: str
    blurb: str
    skills: list[str]
    reachable: bool
    demo: str
    tasks: int = 0
    #: Tone of the most recent task routed here, or "dim" if there was none.
    tone: str = "dim"
    last: str = ""


class SessionRow(BaseModel):
    """One live Claude Code transcript."""

    session_id: str
    project: str
    doing: str
    model: str
    activity: str
    tone: str
    age: str


class HeatCell(BaseModel):
    """One day of the activity heatmap."""

    day: str
    weekday: int
    messages: int
    sessions: int
    #: 0.0 - 1.0, relative to the busiest day in the window.
    level: float


class Analytics(BaseModel):
    """The 30-day picture."""

    real: bool
    source: str
    window_days: int
    sessions: int
    messages: int
    tool_calls: int
    tokens: int
    cost_usd: float
    cost_per_session: float
    busiest_hour: int | None
    hourly: list[int]
    peak_hourly: int
    days: list[HeatCell]
    models: list[dict]
    projects: list[str]


class Dashboard(BaseModel):
    """Everything one render needs."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    heading: str = "J.A.R.V.I.S."
    subheading: str = ""
    #: "live" or "mock". Drives the one piece of colour that means "this costs
    #: money", so it is never inferred client-side.
    mode: str = "mock"
    model: str = ""

    fleet: list[FleetMember] = Field(default_factory=list)
    sessions: list[SessionRow] = Field(default_factory=list)
    analytics: Analytics | None = None
    checks: list[dict] = Field(default_factory=list)
    evals_run: bool = False

    #: The conversation panes, in the shape `console.workspace` already uses.
    turns: list[dict] = Field(default_factory=list)
    questions: list[dict] = Field(default_factory=list)
    cards: list[dict] = Field(default_factory=list)
    open_tasks: int = 0
    approved: int = 0
    held: int = 0
    blocked: int = 0

    #: Where quick capture writes, or "" when capture is unavailable.
    capture_target: str = ""


def fleet_panel(conversation: Conversation, fleet: list[AgentCard] | None = None):
    """The agent cards, with this session's activity folded in."""
    fleet = fleet if fleet is not None else FLEET
    counts: dict[str, int] = {}
    latest: dict[str, TaskStatus] = {}

    for task in conversation.tasks:
        if not task.agent:
            continue
        counts[task.agent] = counts.get(task.agent, 0) + 1
        latest[task.agent] = task.status

    members = []
    for card in fleet:
        status = latest.get(card.name)
        members.append(
            FleetMember(
                name=card.name,
                title=card.title,
                initials=card.initials,
                colour=card.colour,
                blurb=card.blurb,
                skills=card.skills,
                reachable=card.reachable,
                demo=card.demo,
                tasks=counts.get(card.name, 0),
                tone=_STATUS_TONE.get(status, "dim") if status else "dim",
                last=status.value.replace("_", " ") if status else "",
            )
        )
    return members


def sessions_panel(telemetry: Telemetry) -> list[SessionRow]:
    """Live Claude Code transcripts, as rows."""
    return [
        SessionRow(
            session_id=session.session_id[:8],
            project=session.project,
            doing=session.doing,
            model=session.model,
            activity=session.activity.value,
            tone=session.activity.tone,
            age=session.age_label,
        )
        for session in telemetry.live
    ]


def analytics_panel(telemetry: Telemetry) -> Analytics:
    """The heatmap, the clock and the model split.

    `level` is computed here rather than in the page because the page should
    not have to know that a heatmap is normalised against its own peak — and
    because a browser that got the raw counts would have to find the maximum
    itself on every one of thirty cells.
    """
    peak_day = max((day.messages for day in telemetry.days), default=0)
    cells = [
        HeatCell(
            day=day.day.isoformat(),
            weekday=day.day.weekday(),
            messages=day.messages,
            sessions=day.sessions,
            # Floored above zero for any day with activity: a day with one
            # message next to a day with four hundred should still be visible.
            level=max(0.14, day.messages / peak_day) if day.messages and peak_day else 0.0,
        )
        for day in telemetry.days
    ]

    return Analytics(
        real=telemetry.real,
        source=telemetry.source,
        window_days=telemetry.window_days,
        sessions=telemetry.sessions,
        messages=telemetry.messages,
        tool_calls=telemetry.tool_calls,
        tokens=telemetry.tokens,
        cost_usd=round(telemetry.cost_usd, 2),
        cost_per_session=round(telemetry.cost_per_session, 2),
        busiest_hour=telemetry.busiest_hour,
        hourly=telemetry.hourly,
        peak_hourly=max(telemetry.hourly) if telemetry.hourly else 0,
        days=cells,
        models=[
            {
                "family": share.family,
                "sessions": share.sessions,
                "percent": share.percent,
                "cost_usd": round(share.cost_usd, 2),
                "tokens": share.tokens,
            }
            for share in telemetry.models
        ],
        projects=telemetry.projects,
    )


def conversation_panel(state: OverlayState, conversation: Conversation) -> dict:
    """The chat, reusing the shape the existing console already renders."""
    from console.workspace import workspace_state

    return workspace_state(state, conversation)


def build(
    *,
    state: OverlayState,
    conversation: Conversation,
    telemetry: Telemetry,
    diagnostics: Diagnostics,
    mode: str = "mock",
    model: str = "",
    capture_target: str = "",
) -> Dashboard:
    """One dashboard, from the four things it is made of."""
    chat = conversation_panel(state, conversation)
    subheading = (
        f"{telemetry.window_days}-day history from {telemetry.source}"
        if telemetry.real
        else "no Claude Code history found — analytics are fixtures"
    )

    return Dashboard(
        heading="J.A.R.V.I.S.",
        subheading=subheading,
        mode=mode,
        model=model,
        fleet=fleet_panel(conversation),
        sessions=sessions_panel(telemetry),
        analytics=analytics_panel(telemetry),
        checks=[check.model_dump() for check in diagnostics.checks],
        evals_run=diagnostics.evals_run,
        turns=chat["turns"],
        questions=chat["questions"],
        cards=chat["cards"],
        open_tasks=chat["open_tasks"],
        approved=chat["approved"],
        held=chat["held"],
        blocked=chat["blocked"],
        capture_target=capture_target,
    )
