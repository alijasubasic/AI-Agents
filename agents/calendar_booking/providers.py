"""Calendar access behind an interface.

One `Protocol`, one fixture-backed mock, one real implementation shaped for the
Google Calendar API. Mock is the default — see
docs/adr/0002-mock-providers-by-default.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from agents.calendar_booking.fixtures import CALENDARS, PEOPLE
from agents.calendar_booking.models import Attendee, BusyBlock, TimeSlot


class CalendarEvent(BaseModel):
    """An event this agent created."""

    id: str
    title: str
    slot: TimeSlot
    attendee_emails: list[str]


class CalendarProvider(Protocol):
    """The calendar operations this agent needs."""

    def resolve_attendee(self, email: str) -> Attendee | None: ...

    def busy_blocks(self, email: str, start: datetime, end: datetime) -> list[BusyBlock]: ...

    def create_event(
        self, *, title: str, slot: TimeSlot, attendee_emails: list[str]
    ) -> CalendarEvent: ...


class MockCalendar:
    """In-memory calendars over the synthetic fixtures.

    Created events are appended to the relevant calendars, so booking twice in
    one run correctly finds the first booking in the way — the mock behaves like
    a calendar rather than a stub that forgets.
    """

    def __init__(
        self,
        calendars: dict[str, list[BusyBlock]] | None = None,
        people: dict[str, Attendee] | None = None,
    ) -> None:
        source = calendars if calendars is not None else CALENDARS
        self._calendars: dict[str, list[BusyBlock]] = {
            email: list(blocks) for email, blocks in source.items()
        }
        self._people = dict(people if people is not None else PEOPLE)
        self.created: list[CalendarEvent] = []

    def resolve_attendee(self, email: str) -> Attendee | None:
        return self._people.get(email.lower().strip())

    def busy_blocks(self, email: str, start: datetime, end: datetime) -> list[BusyBlock]:
        return [block for block in self._calendars.get(email, []) if block.overlaps(start, end)]

    def create_event(
        self, *, title: str, slot: TimeSlot, attendee_emails: list[str]
    ) -> CalendarEvent:
        event = CalendarEvent(
            id=f"evt-{len(self.created) + 1:03d}",
            title=title,
            slot=slot,
            attendee_emails=list(attendee_emails),
        )
        self.created.append(event)

        block = BusyBlock(start=slot.start, end=slot.end, title=title)
        for email in attendee_emails:
            self._calendars.setdefault(email, []).append(block)

        return event


class GoogleCalendar:
    """Google Calendar-backed provider.

    NOT COVERED BY TESTS. Exercising it would need a real Google account, so
    nothing in CI touches it and it should be treated as unverified. The
    free/busy mapping in particular needs contract tests against a live account
    before anyone relies on it.

    Requires the optional `google` extra and OAuth credentials.
    """

    def __init__(self, credentials_path: str, calendar_id: str = "primary") -> None:
        try:
            from google.oauth2.credentials import Credentials  # type: ignore[import-not-found]
            from googleapiclient.discovery import build  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "GoogleCalendar needs the optional Google client libraries: uv sync --extra google"
            ) from exc

        self._service = build(
            "calendar", "v3", credentials=Credentials.from_authorized_user_file(credentials_path)
        )
        self._calendar_id = calendar_id

    def resolve_attendee(self, email: str) -> Attendee | None:  # pragma: no cover
        raise NotImplementedError(
            "Live attendee resolution is not implemented. Google's API exposes "
            "free/busy but not working hours or time zone per attendee, so this "
            "needs a directory lookup or a local mapping."
        )

    def busy_blocks(
        self, email: str, start: datetime, end: datetime
    ) -> list[BusyBlock]:  # pragma: no cover
        raise NotImplementedError(
            "Live free/busy lookup is not implemented. The freebusy.query call "
            "returns opaque blocks with no titles, so describe_conflicts() would "
            "degrade — that tradeoff needs deciding before this is written."
        )

    def create_event(
        self, *, title: str, slot: TimeSlot, attendee_emails: list[str]
    ) -> CalendarEvent:  # pragma: no cover
        raise NotImplementedError("Live event creation is not implemented yet.")
