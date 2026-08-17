"""Calendar booking: find mutually free times across time zones, propose, book.

The model decides who and how long. `scheduling.py` decides when.
"""

from agents.calendar_booking.agent import CalendarBookingAgent
from agents.calendar_booking.models import (
    Attendee,
    BookingRequest,
    BookingResult,
    BusyBlock,
    MeetingProposal,
    ProposalDraft,
    SchedulingPolicy,
    TimeSlot,
    WorkingHours,
)
from agents.calendar_booking.providers import (
    CalendarEvent,
    CalendarProvider,
    GoogleCalendar,
    MockCalendar,
)
from agents.calendar_booking.scheduling import (
    blocked_periods,
    describe_conflicts,
    find_slots,
    merge_blocks,
)

__all__ = [
    "Attendee",
    "BookingRequest",
    "BookingResult",
    "BusyBlock",
    "CalendarBookingAgent",
    "CalendarEvent",
    "CalendarProvider",
    "GoogleCalendar",
    "MeetingProposal",
    "MockCalendar",
    "ProposalDraft",
    "SchedulingPolicy",
    "TimeSlot",
    "WorkingHours",
    "blocked_periods",
    "describe_conflicts",
    "find_slots",
    "merge_blocks",
]
