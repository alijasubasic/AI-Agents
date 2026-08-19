"""Data models for calendar booking.

The same split as the triage agent, for the same reason:

* The **model** decides what kind of meeting this is — how long, roughly when,
  what to call it, how to word the confirmation.
* The **code** decides when everyone is actually free. Intersecting busy blocks
  across time zones is arithmetic, and arithmetic should not be delegated to a
  language model that might be plausibly wrong.

All datetimes crossing a boundary are timezone-aware and stored in UTC. Local
wall-clock time exists only for display and for working-hours checks.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

#: Monday=0 … Sunday=6, matching `datetime.weekday()`.
WEEKDAYS = frozenset({0, 1, 2, 3, 4})


def _require_aware(value: datetime) -> datetime:
    """Reject naive datetimes at the boundary.

    A naive datetime in a scheduling system is a bug waiting to happen: it is
    silently interpreted as whatever the server's locale is. Better to refuse it
    than to book a meeting an hour off.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


class WorkingHours(BaseModel):
    """When one person is willing to be in a meeting, in their own time zone."""

    timezone: str = Field(description="IANA time zone name, e.g. 'Europe/Berlin'.")
    start: time = time(9, 0)
    end: time = time(17, 0)
    weekdays: frozenset[int] = WEEKDAYS

    model_config = {"frozen": True}

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        # Fail here, with the offending name, rather than deep inside the
        # slot search where the cause is much harder to see.
        ZoneInfo(value)
        return value

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def contains(self, moment: datetime) -> bool:
        """True if `moment` falls inside these working hours."""
        local = _require_aware(moment).astimezone(self.zone)
        if local.weekday() not in self.weekdays:
            return False
        return self.start <= local.time() < self.end

    def covers(self, start: datetime, end: datetime) -> bool:
        """True if the whole interval fits inside one working day.

        Checked as a closed interval on the end: a meeting finishing exactly at
        17:00 is fine, one finishing at 17:01 is not. The end is also required
        to land on the same local day, so nothing straddles midnight.
        """
        start_utc, end_utc = _require_aware(start), _require_aware(end)
        if not self.contains(start_utc):
            return False

        local_end = end_utc.astimezone(self.zone)
        local_start = start_utc.astimezone(self.zone)
        if local_end.date() != local_start.date():
            return False
        return local_end.time() <= self.end


class Attendee(BaseModel):
    """One participant, with their own working hours and time zone."""

    email: str
    name: str = ""
    working_hours: WorkingHours

    model_config = {"frozen": True}

    @property
    def label(self) -> str:
        return self.name or self.email


class BusyBlock(BaseModel):
    """A period when someone is unavailable."""

    start: datetime
    end: datetime
    title: str = ""

    _normalise_start = field_validator("start")(_require_aware)
    _normalise_end = field_validator("end")(_require_aware)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: datetime, info) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("busy block must end after it starts")
        return value

    def overlaps(self, start: datetime, end: datetime) -> bool:
        """True if this block intersects the given interval.

        Touching intervals do not overlap: a block ending at 10:00 leaves 10:00
        free as a start time.
        """
        return self.start < end and start < self.end

    def padded(self, minutes: int) -> BusyBlock:
        """This block widened by `minutes` on both sides."""
        delta = timedelta(minutes=minutes)
        return BusyBlock(
            start=self.start - delta,
            end=self.end + delta,
            title=self.title,
        )


class TimeSlot(BaseModel):
    """A candidate meeting time."""

    start: datetime
    end: datetime

    _normalise_start = field_validator("start")(_require_aware)
    _normalise_end = field_validator("end")(_require_aware)

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    def local(self, timezone: str) -> str:
        """Render this slot in one attendee's time zone, for confirmations."""
        zone = ZoneInfo(timezone)
        start, end = self.start.astimezone(zone), self.end.astimezone(zone)
        return f"{start:%a %d %b %H:%M}-{end:%H:%M} ({start:%Z})"

    def describe_for(self, attendees: list[Attendee]) -> str:
        """Render the slot once per distinct attendee time zone."""
        zones: list[str] = []
        for attendee in attendees:
            tz = attendee.working_hours.timezone
            if tz not in zones:
                zones.append(tz)
        return " | ".join(self.local(tz) for tz in zones)


class SchedulingPolicy(BaseModel):
    """Deterministic rules governing which slots are offerable.

    Like the triage agent's escalation policy, this is deliberately not
    something the model gets to influence — it is configuration, and every rule
    in it is unit-tested.
    """

    #: Gap enforced on both sides of every existing meeting. Back-to-back calls
    #: are how calendars become unusable.
    buffer_minutes: int = Field(default=15, ge=0)

    #: Candidate start times land on this grid. 15 means :00, :15, :30, :45.
    granularity_minutes: int = Field(default=15, gt=0)

    #: Nothing may be booked sooner than this. Protects against an agent filling
    #: someone's next hour.
    min_notice_hours: int = Field(default=12, ge=0)

    #: How far ahead to search.
    search_horizon_days: int = Field(default=14, gt=0)

    #: How many options to offer.
    max_suggestions: int = Field(default=3, gt=0)

    #: Offering three slots in the same afternoon is not really offering three
    #: options. Spreading them across days gives the other side a real choice.
    max_suggestions_per_day: int = Field(default=1, gt=0)

    model_config = {"frozen": True}


class BookingRequest(BaseModel):
    """What the model extracted from the incoming request.

    Field descriptions are prompt text — this schema is what the API shows the
    model as the shape of its answer.
    """

    title: str = Field(description="Short meeting title, e.g. 'Intro call — Kestrel Systems'.")
    duration_minutes: int = Field(
        ge=5,
        le=480,
        description="Meeting length in minutes. Use 30 unless the request states otherwise.",
    )
    attendee_emails: list[str] = Field(
        description="Email addresses of everyone who must attend, excluding the organiser."
    )
    earliest_date: str | None = Field(
        default=None,
        description=(
            "Earliest acceptable date as YYYY-MM-DD, if the request constrains it. "
            "Null when the sender said nothing about timing."
        ),
    )
    latest_date: str | None = Field(
        default=None,
        description="Latest acceptable date as YYYY-MM-DD, or null if unconstrained.",
    )
    notes: str = Field(
        default="",
        description="Anything about timing the schedule cannot express, e.g. 'prefers afternoons'.",
    )


class ProposalDraft(BaseModel):
    """What the model returns: the parsed request plus the wording.

    Note what is *not* here — the times. The model may describe slots it saw in
    a tool result, but the authoritative slot list is recomputed by the
    scheduling engine afterwards. Times are never parsed back out of prose.
    """

    request: BookingRequest
    message: str = Field(
        description=(
            "The proposal text to send, in the configured voice. Mention the "
            "times exactly as the find_available_slots tool reported them, "
            "including time zones. Never state a time the tool did not give you."
        )
    )


class MeetingProposal(BaseModel):
    """The offer sent back to the requester."""

    request: BookingRequest
    slots: list[TimeSlot]
    message: str = Field(default="", description="The proposal text, in the configured voice.")

    @property
    def has_options(self) -> bool:
        return bool(self.slots)


class BookingResult(BaseModel):
    """The outcome of actually booking one slot."""

    booked: bool
    slot: TimeSlot | None = None
    event_id: str | None = None
    confirmation: str = ""
    failure_reason: str | None = None

    cost_usd: float = 0.0
    duration_ms: float = 0.0
