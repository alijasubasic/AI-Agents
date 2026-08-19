"""Runnable demonstration of the calendar booking agent.

    python -m agents.calendar_booking.demo

Three scenarios on synthetic calendars, with the clock pinned to Thursday
5 March 2026 so output is identical on every run. No API key, no Google
account, no network.
"""

from __future__ import annotations

from agents.calendar_booking.agent import CalendarBookingAgent
from agents.calendar_booking.fixtures import ORGANISER, REFERENCE_NOW
from agents.calendar_booking.models import BookingResult, MeetingProposal
from agents.calendar_booking.providers import MockCalendar
from agents.calendar_booking.scripted import REQUESTS, provider_for
from core.config import Settings
from core.console import configure_stdout


def run_scenario(
    scenario: str,
    *,
    settings: Settings | None = None,
    calendar: MockCalendar | None = None,
    book_choice: int | None = 0,
) -> tuple[MeetingProposal, BookingResult | None]:
    """Propose times for one scenario, and optionally book the first option."""
    agent = CalendarBookingAgent(
        provider=provider_for(scenario),
        calendar=calendar or MockCalendar(),
        organiser=ORGANISER,
        settings=settings or Settings.from_env(),
        now=REFERENCE_NOW,
    )

    proposal = agent.propose(REQUESTS[scenario])
    if book_choice is None or not proposal.has_options:
        return proposal, None
    return proposal, agent.book(proposal, book_choice)


def _print(scenario: str, proposal: MeetingProposal, booking: BookingResult | None) -> None:
    print(f"\n{'=' * 74}")
    print(f"{scenario}: {REQUESTS[scenario]}")
    print("=" * 74)
    print(
        f"  parsed: {proposal.request.title!r}, {proposal.request.duration_minutes} min, "
        f"with {', '.join(proposal.request.attendee_emails)}"
    )

    if proposal.has_options:
        print("\n  openings found by the scheduling engine:")
        for index, slot in enumerate(proposal.slots, start=1):
            print(f"    {index}. {slot.local('Europe/Berlin')}")
            print(f"       {slot.local('America/New_York')}")
    else:
        print("\n  no openings")

    print("\n  proposal text:")
    for line in proposal.message.splitlines():
        print(f"    {line}")

    if booking is None:
        return
    if booking.booked:
        print("\n  booked:")
        for line in booking.confirmation.splitlines():
            print(f"    {line}")
    else:
        print(f"\n  not booked: {booking.failure_reason}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("calendar-booking demo")
    print(f"mode={settings.mode}  model={settings.model}")
    print(f"clock pinned to {REFERENCE_NOW:%a %d %b %Y %H:%M} UTC")

    for scenario in ("internal", "transatlantic", "impossible"):
        proposal, booking = run_scenario(scenario, settings=settings)
        _print(scenario, proposal, booking)

    print(f"\n{'=' * 74}")
    print(
        "The times above were computed by scheduling.py, not by the model.\n"
        "The model chose who and how long; the engine decided when. Booking\n"
        "itself involves no model call at all."
    )


if __name__ == "__main__":
    main()
