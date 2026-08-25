"""Google Calendar, behind the `CalendarProvider` interface.

The mapping that matters is free/busy. Google's `freebusy.query` returns
opaque intervals with no titles, which is exactly right for this agent: it
needs to know *when* somebody is unavailable and has no business knowing what
the meeting is. `BusyBlock.title` is therefore left empty rather than filled
from the event list, and that is a deliberate loss of information.

**What this cannot do, and why it is not a bug.** `resolve_attendee` needs a
person's working hours and time zone. Google exposes neither for anyone but
the authenticated user — `calendar.readonly` gives you their free/busy, not
their office hours. Guessing 09:00–17:00 in the organiser's zone would produce
proposals that look authoritative and are wrong for anybody in another
country, which is the specific failure `calendar-booking` exists to avoid. So
attendees come from a local roster the operator maintains, and an unknown
address is an unknown address.
"""

from __future__ import annotations

from datetime import datetime

from agents.calendar_booking.models import Attendee, BusyBlock, TimeSlot
from agents.calendar_booking.providers import CalendarEvent
from integrations.google.auth import CALENDAR_SCOPES, service

#: Google caps a free/busy query at this many calendars per request.
MAX_CALENDARS_PER_QUERY = 50


class GoogleCalendar:
    """Live calendar access for one authenticated account.

    `roster` supplies working hours and time zones, which Google will not. It
    is the same shape as the fixtures, so pointing this at real people is a
    dictionary, not a code change.
    """

    def __init__(
        self,
        *,
        roster: dict[str, Attendee] | None = None,
        calendar_id: str = "primary",
        allow_writes: bool = False,
    ) -> None:
        self._roster = {email.lower(): person for email, person in (roster or {}).items()}
        self._calendar_id = calendar_id
        #: Creating an event puts something in other people's calendars, so it
        #: is off unless somebody turned it on. The same reasoning as
        #: `gmail.send` being outside the default scopes.
        self._allow_writes = allow_writes
        self._service = service("calendar", "v3", scopes=CALENDAR_SCOPES)

    def resolve_attendee(self, email: str) -> Attendee | None:
        """From the local roster. See the module docstring for why."""
        return self._roster.get(email.lower().strip())

    def busy_blocks(self, email: str, start: datetime, end: datetime) -> list[BusyBlock]:
        """Every interval Google reports as busy, with no titles attached."""
        response = (
            self._service.freebusy()
            .query(
                body={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "items": [{"id": email}],
                }
            )
            .execute()
        )

        calendars = response.get("calendars", {})
        entry = calendars.get(email, {})
        if entry.get("errors"):
            # A calendar nobody shared reads as "no information", not "free".
            # Treating an error as an empty calendar is how an agent books a
            # meeting on top of one it could not see.
            raise PermissionError(
                f"Google returned no free/busy for {email}: {entry['errors']}. "
                "The calendar is probably not shared with the authenticated account."
            )

        blocks = []
        for period in entry.get("busy", []):
            blocks.append(
                BusyBlock(
                    start=datetime.fromisoformat(period["start"].replace("Z", "+00:00")),
                    end=datetime.fromisoformat(period["end"].replace("Z", "+00:00")),
                    title="",
                )
            )
        return blocks

    def create_event(
        self, *, title: str, slot: TimeSlot, attendee_emails: list[str]
    ) -> CalendarEvent:
        """Create the meeting. Refuses unless writes were explicitly enabled."""
        if not self._allow_writes:
            raise PermissionError(
                "GoogleCalendar was built with allow_writes=False, so it will not "
                "create events. This is the default: booking puts an entry in "
                "other people's calendars."
            )

        created = (
            self._service.events()
            .insert(
                calendarId=self._calendar_id,
                sendUpdates="all",
                body={
                    "summary": title,
                    "start": {"dateTime": slot.start.isoformat()},
                    "end": {"dateTime": slot.end.isoformat()},
                    "attendees": [{"email": email} for email in attendee_emails],
                },
            )
            .execute()
        )

        return CalendarEvent(
            id=created["id"],
            title=title,
            slot=slot,
            attendee_emails=list(attendee_emails),
        )
