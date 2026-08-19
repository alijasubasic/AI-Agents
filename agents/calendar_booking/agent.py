"""The calendar booking agent.

Two phases, split along a deliberate line:

    propose()  model + code — the model reads the request and writes the offer,
               the engine decides which times are actually offerable
    book()     code only    — verification and event creation involve no model

Booking is the irreversible half, so it does not depend on a model being
available, correct, or even reachable. Everything `book()` needs has already
been decided by the time it is called.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from agents.calendar_booking.fixtures import VOICE_GUIDE
from agents.calendar_booking.models import (
    Attendee,
    BookingRequest,
    BookingResult,
    BusyBlock,
    MeetingProposal,
    ProposalDraft,
    SchedulingPolicy,
    TimeSlot,
)
from agents.calendar_booking.providers import CalendarProvider
from agents.calendar_booking.scheduling import describe_conflicts, find_slots
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider
from core.tools import Tool, ToolRegistry

SYSTEM_PROMPT = """\
You schedule meetings on behalf of {organiser}.

Read the request, work out who needs to attend and how long the meeting should
be, then call find_available_slots to get real openings. Write a short proposal
offering the times it returned.

Rules:

- Always call find_available_slots before writing the proposal. You cannot see
  anyone's calendar and must not reason about availability yourself.
- Quote the times exactly as the tool reported them, time zones included.
  Never adjust, round, or translate a time yourself.
- If the tool returns no openings, say so plainly and suggest widening the
  window. Do not invent a time to be helpful.
- Default to 30 minutes unless the request says otherwise.

VOICE:
{voice}
"""


def _parse_date(value: str | None, zone: ZoneInfo) -> datetime | None:
    """Parse a YYYY-MM-DD string as midnight local time in `zone`."""
    if not value:
        return None
    try:
        naive = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return naive.replace(tzinfo=zone)


class CalendarBookingAgent:
    """Finds mutually free times, proposes them, and books one."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        calendar: CalendarProvider,
        organiser: Attendee,
        policy: SchedulingPolicy | None = None,
        voice: str = VOICE_GUIDE,
        settings: Settings | None = None,
        now: datetime | None = None,
    ) -> None:
        self.calendar = calendar
        self.organiser = organiser
        self.policy = policy or SchedulingPolicy()
        self._now = now
        self._agent = Agent(
            name="calendar-booking",
            system_prompt=SYSTEM_PROMPT.format(organiser=organiser.label, voice=voice.strip()),
            provider=provider,
            tools=self._build_tools(),
            settings=settings,
        )

    # -- public API ------------------------------------------------------

    def propose(self, request_text: str) -> MeetingProposal:
        """Read a scheduling request and offer real openings.

        The model's slot list is never trusted: whatever it wrote, the returned
        slots are recomputed from the calendars by the scheduling engine.
        """
        draft, run = self._agent.run_structured(request_text, ProposalDraft)
        slots = self._find(draft.request)

        return MeetingProposal(
            request=draft.request,
            slots=slots,
            message=draft.message if slots else self._no_options_message(draft.request),
        )

    def book(self, proposal: MeetingProposal, choice: int = 0) -> BookingResult:
        """Book one of the proposed slots. No model involved.

        The slot is re-verified against the calendars immediately before the
        event is created, so a booking made elsewhere between proposing and
        confirming is caught rather than double-booked.
        """
        if not proposal.slots:
            return BookingResult(booked=False, failure_reason="no slots were proposed")
        if not 0 <= choice < len(proposal.slots):
            return BookingResult(
                booked=False,
                failure_reason=f"choice {choice} is outside the {len(proposal.slots)} options",
            )

        slot = proposal.slots[choice]
        attendees = self._attendees(proposal.request.attendee_emails)
        conflicts = describe_conflicts(
            attendees=attendees,
            busy=self._busy(attendees, slot.start, slot.end),
            slot=slot,
            policy=self.policy,
        )
        if conflicts:
            return BookingResult(
                booked=False,
                slot=slot,
                failure_reason="; ".join(conflicts),
            )

        event = self.calendar.create_event(
            title=proposal.request.title,
            slot=slot,
            attendee_emails=[a.email for a in attendees],
        )
        return BookingResult(
            booked=True,
            slot=slot,
            event_id=event.id,
            confirmation=self._confirmation(proposal.request.title, slot, attendees),
        )

    def propose_for(self, request: BookingRequest, message: str = "") -> MeetingProposal:
        """Offer openings for an already-structured request. No model call.

        This is the entry point other agents use. When work arrives as a typed
        `BookingRequest` there is nothing for a model to parse, so paying for
        one would buy only the chance to misread a field that was already
        correct. The model is needed at the human boundary, not between agents.
        """
        slots = self._find(request)
        return MeetingProposal(
            request=request,
            slots=slots,
            message=message
            or (
                self._offer_message(request, slots) if slots else self._no_options_message(request)
            ),
        )

    # -- internals -------------------------------------------------------

    def _build_tools(self) -> ToolRegistry:
        def find_available_slots(
            attendee_emails: list[str],
            duration_minutes: int = 30,
            earliest_date: str | None = None,
            latest_date: str | None = None,
        ) -> str:
            """Find times when everyone is free, respecting working hours and time zones.

            Args:
                attendee_emails: Everyone who must attend, excluding the organiser.
                duration_minutes: Meeting length. Defaults to 30.
                earliest_date: Earliest acceptable date as YYYY-MM-DD, or omit for no limit.
                latest_date: Latest acceptable date as YYYY-MM-DD, or omit for no limit.
            """
            request = BookingRequest(
                title="(pending)",
                duration_minutes=duration_minutes,
                attendee_emails=attendee_emails,
                earliest_date=earliest_date,
                latest_date=latest_date,
            )
            slots = self._find(request)
            if not slots:
                return (
                    "No openings match those constraints. Everyone's working "
                    "hours, existing meetings and the buffer between meetings "
                    "were taken into account."
                )

            attendees = self._attendees(attendee_emails)
            lines = [
                f"{index + 1}. {slot.describe_for(attendees)}" for index, slot in enumerate(slots)
            ]
            return "Available openings:\n" + "\n".join(lines)

        return ToolRegistry([Tool(find_available_slots)])

    def _attendees(self, emails: list[str]) -> list[Attendee]:
        """Resolve attendees, organiser first, skipping anyone unknown."""
        resolved = [self.organiser]
        for email in emails:
            if email.lower().strip() == self.organiser.email.lower():
                continue
            attendee = self.calendar.resolve_attendee(email)
            if attendee is not None and attendee not in resolved:
                resolved.append(attendee)
        return resolved

    def _busy(self, attendees: list[Attendee], start: datetime, end: datetime) -> list[BusyBlock]:
        blocks: list[BusyBlock] = []
        for attendee in attendees:
            blocks.extend(self.calendar.busy_blocks(attendee.email, start, end))
        return blocks

    def _find(self, request: BookingRequest) -> list[TimeSlot]:
        now = (self._now or datetime.now(UTC)).astimezone(UTC)
        zone = self.organiser.working_hours.zone

        earliest = _parse_date(request.earliest_date, zone)
        latest = _parse_date(request.latest_date, zone)
        if latest is not None:
            # A latest date means "that day inclusive", not "midnight that day".
            latest = latest + timedelta(days=1)

        attendees = self._attendees(request.attendee_emails)
        search_end = now + timedelta(days=self.policy.search_horizon_days)

        return find_slots(
            attendees=attendees,
            busy=self._busy(attendees, now, latest or search_end),
            duration_minutes=request.duration_minutes,
            policy=self.policy,
            now=now,
            earliest=earliest,
            latest=latest,
        )

    def _no_options_message(self, request: BookingRequest) -> str:
        return (
            f"I could not find a {request.duration_minutes}-minute opening that "
            f"works for everyone in that window. Widening the date range, or "
            f"shortening the meeting, would give more room."
        )

    def _confirmation(self, title: str, slot: TimeSlot, attendees: list[Attendee]) -> str:
        """Render the confirmation from a template — no model call.

        Confirmations state a committed fact. Generating them would introduce a
        way for the text to disagree with the booking it confirms.
        """
        who = ", ".join(a.label for a in attendees)
        return (
            f"Booked: {title}\n"
            f"{slot.describe_for(attendees)}\n"
            f"With: {who}\n"
            f"Duration: {slot.duration_minutes} minutes"
        )

    def _offer_message(self, request: BookingRequest, slots: list[TimeSlot]) -> str:
        """Render an offer without a model, for agent-to-agent handoffs."""
        attendees = self._attendees(request.attendee_emails)
        lines = [
            f"  {index}. {slot.describe_for(attendees)}" for index, slot in enumerate(slots, 1)
        ]
        return (
            f"{request.duration_minutes} minutes for {request.title}. "
            f"These times work for everyone:\n" + "\n".join(lines)
        )
