"""Synthetic calendars.

Invented people, invented meetings. The week is fixed — Thursday 5 March 2026
onwards — so the demo and the tests produce identical output on every run.

That week was chosen deliberately: US daylight saving time begins on Sunday
8 March 2026, while European summer time does not start until 29 March. The
Berlin/New York overlap window therefore *changes shape* in the middle of the
search horizon, which is exactly the kind of thing a hand-rolled scheduler gets
wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from agents.calendar_booking.models import Attendee, BusyBlock, WorkingHours

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")

#: Fixed "current time" for the demo: Thursday 5 March 2026, 08:00 UTC.
REFERENCE_NOW = datetime(2026, 3, 5, 8, 0, tzinfo=UTC)


def berlin(day: int, hour: int, minute: int = 0) -> datetime:
    """A local Berlin wall-clock time in March 2026."""
    return datetime(2026, 3, day, hour, minute, tzinfo=BERLIN)


def new_york(day: int, hour: int, minute: int = 0) -> datetime:
    """A local New York wall-clock time in March 2026."""
    return datetime(2026, 3, day, hour, minute, tzinfo=NEW_YORK)


# --- People -------------------------------------------------------------

BERLIN_HOURS = WorkingHours(timezone="Europe/Berlin", start=time(9, 0), end=time(17, 0))
NEW_YORK_HOURS = WorkingHours(timezone="America/New_York", start=time(9, 0), end=time(17, 0))

ORGANISER = Attendee(
    email="alija@example.com",
    name="Alija",
    working_hours=BERLIN_HOURS,
)

NINA = Attendee(
    email="n.brandt@example.com",
    name="Nina Brandt",
    working_hours=BERLIN_HOURS,
)

TOBIAS = Attendee(
    email="t.berger@meridian-consulting.example",
    name="Tobias Berger",
    working_hours=BERLIN_HOURS,
)

DANA = Attendee(
    email="d.reyes@kestrel-systems.example",
    name="Dana Reyes",
    working_hours=NEW_YORK_HOURS,
)

PEOPLE: dict[str, Attendee] = {person.email: person for person in (ORGANISER, NINA, TOBIAS, DANA)}


# --- Calendars ----------------------------------------------------------
# March 2026: the 5th is a Thursday, the 6th a Friday, the 7th–8th a weekend,
# the 9th a Monday.

CALENDARS: dict[str, list[BusyBlock]] = {
    ORGANISER.email: [
        BusyBlock(start=berlin(6, 9, 0), end=berlin(6, 9, 30), title="Daily standup"),
        BusyBlock(start=berlin(6, 11, 0), end=berlin(6, 12, 30), title="Supplier review"),
        BusyBlock(start=berlin(9, 9, 0), end=berlin(9, 12, 0), title="Quarterly planning"),
        BusyBlock(start=berlin(10, 14, 0), end=berlin(10, 15, 0), title="1:1 with Nina"),
        BusyBlock(start=berlin(11, 9, 0), end=berlin(11, 17, 0), title="Offsite"),
    ],
    NINA.email: [
        BusyBlock(start=berlin(6, 10, 0), end=berlin(6, 11, 0), title="Design sync"),
        BusyBlock(start=berlin(9, 13, 0), end=berlin(9, 14, 0), title="Interview"),
        BusyBlock(start=berlin(10, 14, 0), end=berlin(10, 15, 0), title="1:1 with Alija"),
    ],
    TOBIAS.email: [
        BusyBlock(start=berlin(6, 14, 0), end=berlin(6, 16, 0), title="Client workshop"),
        BusyBlock(start=berlin(10, 9, 0), end=berlin(10, 11, 0), title="Board call"),
    ],
    DANA.email: [
        BusyBlock(start=new_york(6, 9, 0), end=new_york(6, 10, 0), title="Team sync"),
        BusyBlock(start=new_york(9, 9, 0), end=new_york(9, 10, 30), title="Sprint review"),
    ],
}


#: Voice for proposal and confirmation text, matching the triage agent's.
VOICE_GUIDE = """\
Write like a competent, unhurried colleague:

- Plain English, no filler openers.
- Offer the times plainly and say which time zone they are in.
- One short sentence of context at most. Nobody reads a long scheduling email.
- Never invent a time that was not given to you in a tool result.
"""
