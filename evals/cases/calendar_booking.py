"""Eval cases for the calendar booking agent.

The scheduling engine is pure arithmetic, so almost everything here is exact
rather than approximate — which is the point of having moved that work out of
the model in the first place.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from agents.calendar_booking.agent import CalendarBookingAgent
from agents.calendar_booking.fixtures import DANA, ORGANISER, REFERENCE_NOW
from agents.calendar_booking.models import (
    Attendee,
    BusyBlock,
    SchedulingPolicy,
    WorkingHours,
)
from agents.calendar_booking.providers import MockCalendar
from agents.calendar_booking.scheduling import find_slots, merge_blocks
from agents.calendar_booking.scripted import REQUESTS, provider_for
from core.config import Settings
from evals.models import Expectation, Layer, Score
from evals.registry import case
from evals.scoring import at_most, combine, equals, is_false, is_true

AGENT = "calendar-booking"

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
BERLIN_HOURS = WorkingHours(timezone="Europe/Berlin", start=time(9), end=time(17))
NEW_YORK_HOURS = WorkingHours(timezone="America/New_York", start=time(9), end=time(17))
ALICE = Attendee(email="a@example.test", name="Alice", working_hours=BERLIN_HOURS)
BOB = Attendee(email="b@example.test", name="Bob", working_hours=NEW_YORK_HOURS)

NOW = datetime(2026, 3, 5, 8, 0, tzinfo=UTC)


def bt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=BERLIN)


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def policy(**overrides) -> SchedulingPolicy:
    base = {
        "buffer_minutes": 0,
        "granularity_minutes": 30,
        "min_notice_hours": 0,
        "max_suggestions": 3,
        "max_suggestions_per_day": 1,
    }
    return SchedulingPolicy(**{**base, **overrides})


def _propose(scenario: str):
    agent = CalendarBookingAgent(
        provider=provider_for(scenario),
        calendar=MockCalendar(),
        organiser=ORGANISER,
        settings=Settings(trace_enabled=False),
        now=REFERENCE_NOW,
    )
    return agent, agent.propose(REQUESTS[scenario])


# --- The engine ---------------------------------------------------------


@case(
    id="booking-skips-the-weekend",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Slots land on working days only, one per day.",
)
def _() -> Score:
    slots = find_slots(attendees=[ALICE], busy=[], duration_minutes=30, policy=policy(), now=NOW)
    return equals([s.start for s in slots], [bt(5, 9), bt(6, 9), bt(9, 9)], label="slots")


@case(
    id="booking-buffer-applies-both-sides",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A 09:00-10:00 meeting with a 15-minute buffer blocks 08:45-10:15.",
)
def _() -> Score:
    slots = find_slots(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(5, 9), end=bt(5, 10), title="Standup")],
        duration_minutes=30,
        policy=policy(buffer_minutes=15, granularity_minutes=15),
        now=NOW,
    )
    return equals(slots[0].start, bt(5, 10, 15), label="first slot")


@case(
    id="booking-respects-minimum-notice",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Nothing is offered inside the notice window.",
)
def _() -> Score:
    slots = find_slots(
        attendees=[ALICE],
        busy=[],
        duration_minutes=30,
        policy=policy(min_notice_hours=24),
        now=NOW,
    )
    return equals(slots[0].start, bt(6, 9), label="first slot")


@case(
    id="booking-meeting-must-fit-the-working-day",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A 60-minute meeting is not squeezed into a 30-minute gap before 17:00.",
)
def _() -> Score:
    slots = find_slots(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(5, 9), end=bt(5, 16, 30), title="All day")],
        duration_minutes=60,
        policy=policy(max_suggestions=1),
        now=NOW,
    )
    return equals(slots[0].start, bt(6, 9), label="first slot")


@case(
    id="booking-touching-blocks-merge",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="09:00-10:00 followed by 10:00-11:00 is one unavailable stretch.",
)
def _() -> Score:
    merged = merge_blocks(
        [
            BusyBlock(start=bt(5, 9), end=bt(5, 10)),
            BusyBlock(start=bt(5, 10), end=bt(5, 11)),
        ]
    )
    return combine(
        equals(len(merged), 1, label="block count"),
        equals(merged[0].end, bt(5, 11), label="merged end"),
    )


@case(
    id="booking-no-openings-is-an-answer",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An impossible window returns an empty list rather than raising.",
)
def _() -> Score:
    slots = find_slots(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(6, 0), end=bt(7, 0), title="Blocked")],
        duration_minutes=30,
        policy=policy(),
        now=NOW,
        earliest=bt(6, 0),
        latest=bt(7, 0),
    )
    return equals(slots, [], label="slots")


# --- Time zones ---------------------------------------------------------


@case(
    id="booking-offers-only-the-overlap",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Berlin and New York share only the Berlin afternoon.",
)
def _() -> Score:
    slots = find_slots(
        attendees=[ALICE, BOB],
        busy=[],
        duration_minutes=60,
        policy=policy(max_suggestions=1),
        now=NOW,
    )
    return combine(
        equals(slots[0].start, utc(5, 14), label="slot start"),
        equals(slots[0].start.astimezone(NEW_YORK).hour, 9, label="New York hour"),
    )


@case(
    id="booking-follows-the-daylight-saving-shift",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The overlap moves an hour in UTC when US summer time begins on 8 March.",
)
def _() -> Score:
    thursday, friday, monday = find_slots(
        attendees=[ALICE, BOB],
        busy=[],
        duration_minutes=60,
        policy=policy(max_suggestions=3),
        now=NOW,
    )
    return combine(
        equals(thursday.start, utc(5, 14), label="before DST"),
        equals(friday.start, utc(6, 14), label="before DST"),
        equals(monday.start, utc(9, 13), label="after DST"),
        equals(
            {s.start.astimezone(NEW_YORK).hour for s in (thursday, friday, monday)},
            {9},
            label="local New York hour unchanged",
        ),
    )


@case(
    id="booking-naive-datetimes-are-refused",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A datetime without a time zone is rejected rather than assumed.",
)
def _() -> Score:
    try:
        BERLIN_HOURS.contains(datetime(2026, 3, 5, 10, 0))
    except ValueError:
        return Score.hit("naive datetime refused")
    return Score.miss("a naive datetime was silently accepted")


# --- The agent ----------------------------------------------------------


@case(
    id="booking-offers-at-most-three-options",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The proposal never exceeds the configured number of options.",
)
def _() -> Score:
    _agent, proposal = _propose("internal")
    return at_most(len(proposal.slots), SchedulingPolicy().max_suggestions, label="options")


@case(
    id="booking-every-option-suits-everyone",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Offered slots fall inside every attendee's working day.",
)
def _() -> Score:
    _agent, proposal = _propose("transatlantic")
    ok = all(
        ORGANISER.working_hours.covers(s.start, s.end) and DANA.working_hours.covers(s.start, s.end)
        for s in proposal.slots
    )
    return combine(
        is_true(bool(proposal.slots), label="options offered"),
        is_true(ok, label="all options inside working hours"),
    )


@case(
    id="booking-impossible-request-invents-nothing",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="With no openings, the model's wording is discarded for a generated one.",
)
def _() -> Score:
    _agent, proposal = _propose("impossible")
    return combine(
        equals(proposal.slots, [], label="slots"),
        is_true("could not find" in proposal.message, label="deterministic fallback used"),
    )


@case(
    id="booking-double-booking-is-refused",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A slot taken between proposing and confirming is caught.",
)
def _() -> Score:
    calendar = MockCalendar()
    agent = CalendarBookingAgent(
        provider=provider_for("internal"),
        calendar=calendar,
        organiser=ORGANISER,
        settings=Settings(trace_enabled=False),
        now=REFERENCE_NOW,
    )
    proposal = agent.propose(REQUESTS["internal"])
    calendar.create_event(
        title="Something else", slot=proposal.slots[0], attendee_emails=[ORGANISER.email]
    )
    result = agent.book(proposal, 0)
    return combine(
        is_false(result.booked, label="booked"),
        is_true("Something else" in (result.failure_reason or ""), label="clash named"),
    )


@case(
    id="booking-handoff-costs-no-model-call",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="propose_for() runs the engine and consults no model.",
)
def _() -> Score:
    from agents.calendar_booking.models import BookingRequest
    from core.llm import MockProvider, text_response

    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = CalendarBookingAgent(
        provider=provider,
        calendar=MockCalendar(),
        organiser=ORGANISER,
        settings=Settings(trace_enabled=False),
        now=REFERENCE_NOW,
    )
    agent.propose_for(
        BookingRequest(title="Handoff", duration_minutes=30, attendee_emails=[DANA.email])
    )
    return equals(provider.calls, [], label="model calls")


# --- Known gaps ---------------------------------------------------------


@case(
    id="booking-half-hour-offset-zones",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Candidate times align in UTC, so :45-offset zones get odd local minutes.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Asia/Kathmandu is UTC+5:45, which no 15- or 30-minute UTC grid divides, "
        "so local starts land on :45 and :15. Half-hour offsets like Kolkata are "
        "unaffected. Aligning in the organiser's zone would fix it."
    ),
)
def _() -> Score:
    kathmandu = Attendee(
        email="k@example.test",
        name="Kiran",
        working_hours=WorkingHours(timezone="Asia/Kathmandu", start=time(9), end=time(17)),
    )
    slots = find_slots(
        attendees=[kathmandu], busy=[], duration_minutes=30, policy=policy(), now=NOW
    )
    local = slots[0].start.astimezone(ZoneInfo("Asia/Kathmandu"))
    return is_true(local.minute in (0, 30), label="clean local start time")


@case(
    id="booking-no-recurring-events",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Recurrence rules are not modelled at all.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Fixtures and providers hold single blocks. Real calendars are mostly "
        "recurring meetings, and expanding those correctly is a meaningful "
        "piece of work that has not been started."
    ),
)
def _() -> Score:
    return is_true(hasattr(BusyBlock, "recurrence"), label="busy blocks model recurrence")
