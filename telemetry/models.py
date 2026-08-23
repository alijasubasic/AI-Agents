"""What a Claude Code transcript tells you, once you stop reading the words.

Every model in this file is deliberately **content-free**. A session transcript
is somebody's actual work — client names, half-written emails, credentials they
pasted and regretted. A dashboard that renders it is a dashboard you cannot
screen-share.

So the rule this package is built around:

    counts, timestamps, model ids and tool *names* leave the parser.
    Message text never does.

There is no field below that can hold a sentence a person or a model wrote.
That is not an oversight to be fixed later; it is the reason this is safe to
point at a real home directory.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Activity(StrEnum):
    """What a session looks like it is doing right now.

    Derived from the last few records rather than from any process list: a
    transcript that stopped growing four minutes ago is idle whatever `ps` says.
    """

    WORKING = "working"
    WAITING = "waiting"
    IDLE = "idle"

    @property
    def tone(self) -> str:
        """CSS class name, so the page never maps this itself."""
        return {
            Activity.WORKING: "ok",
            Activity.WAITING: "hold",
            Activity.IDLE: "dim",
        }[self]


class LiveSession(BaseModel):
    """A transcript that changed recently enough to be worth showing.

    `tool` is the *name* of the tool in flight — "Bash", "Edit" — and never its
    input. The source this idea comes from renders the input too, which is how
    a dashboard ends up displaying the contents of a file somebody just opened.
    """

    session_id: str
    project: str
    model: str = ""
    tool: str | None = None
    subagent: str | None = None
    activity: Activity = Activity.IDLE
    age_seconds: int = 0
    #: Messages seen in the tail window, not the whole file. Cheap and enough
    #: to tell a long session from one that just started.
    recent_messages: int = 0

    @property
    def age_label(self) -> str:
        if self.age_seconds < 60:
            return f"{self.age_seconds}s ago"
        if self.age_seconds < 3600:
            return f"{self.age_seconds // 60}m ago"
        return f"{self.age_seconds // 3600}h ago"

    @property
    def doing(self) -> str:
        """One phrase for the row, with no transcript content in it."""
        if self.subagent:
            return f"delegating to {self.subagent}"
        if self.tool:
            return f"running {self.tool}"
        return self.activity.value


class SessionSummary(BaseModel):
    """One whole transcript, reduced to numbers.

    Cached against the file's modification time: a finished session never
    changes again, so re-reading a hundred megabytes of history on every
    dashboard refresh would be work done purely to get the same answer.
    """

    session_id: str
    project: str
    model: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    messages: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    #: Local hour of day -> records in that hour. Drives the peak-hours panel.
    hours: dict[int, int] = Field(default_factory=dict)
    #: Local date -> messages on that date.
    #:
    #: Sessions are not one-day things. This one has run for days, and
    #: attributing all of its work to `started_at` — which is what the source
    #: dashboard does — leaves today's heatmap cell empty while you are
    #: visibly typing into it. A panel that says nothing happened today is one
    #: you stop believing.
    daily: dict[date, int] = Field(default_factory=dict)
    #: File mtime in seconds, the cache key.
    mtime: float = 0.0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    @property
    def day(self) -> date | None:
        return self.started_at.date() if self.started_at else None


class DayActivity(BaseModel):
    """One cell of the heatmap."""

    day: date
    sessions: int = 0
    messages: int = 0
    cost_usd: float = 0.0


class ModelShare(BaseModel):
    """How much of the work one model family did."""

    family: str
    sessions: int
    percent: int
    cost_usd: float
    tokens: int


class Telemetry(BaseModel):
    """Everything the dashboard knows about how this machine has been used.

    `real` distinguishes a genuine scan from the synthetic fallback. The
    dashboard says which one it is on screen, because a heatmap that quietly
    shows fixtures is worse than an empty one — you would trust it.
    """

    real: bool = False
    source: str = ""
    scanned_at: datetime | None = None
    window_days: int = 30

    sessions: int = 0
    messages: int = 0
    tool_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0

    days: list[DayActivity] = Field(default_factory=list)
    #: 24 buckets, index = local hour.
    hourly: list[int] = Field(default_factory=lambda: [0] * 24)
    models: list[ModelShare] = Field(default_factory=list)
    live: list[LiveSession] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)

    @property
    def busiest_hour(self) -> int | None:
        """The hour with the most records, or None if nothing was seen."""
        if not any(self.hourly):
            return None
        return max(range(24), key=lambda h: self.hourly[h])

    @property
    def favourite(self) -> ModelShare | None:
        return self.models[0] if self.models else None

    @property
    def cost_per_session(self) -> float:
        return self.cost_usd / self.sessions if self.sessions else 0.0
