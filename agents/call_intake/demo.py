"""Runnable demonstration of the call intake agent.

    python -m agents.call_intake.demo

Five synthetic transcripts on the mock provider — no API key, no telephony, no
network. Between them they cover a clean booking, a complaint, a hallucinated
extraction, an instruction-override attempt, and a cold sales call.
"""

from __future__ import annotations

from agents.calendar_booking.agent import CalendarBookingAgent
from agents.calendar_booking.fixtures import ORGANISER
from agents.calendar_booking.fixtures import REFERENCE_NOW as CALENDAR_NOW
from agents.calendar_booking.providers import MockCalendar
from agents.call_intake.agent import CallIntakeAgent
from agents.call_intake.fixtures import TRANSCRIPTS
from agents.call_intake.models import IntakeResult
from agents.call_intake.scripted import provider_for
from core.config import Settings
from core.console import configure_stdout
from core.llm import MockProvider, text_response


def build_booking_agent(settings: Settings) -> tuple[CalendarBookingAgent, MockProvider]:
    """Wire up the booking agent for delegation.

    Its provider is scripted with one response that is never consumed: handoffs
    between agents go through `propose_for`, which runs the scheduling engine
    and calls no model. The returned provider lets tests prove that.
    """
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = CalendarBookingAgent(
        provider=provider,
        calendar=MockCalendar(),
        organiser=ORGANISER,
        settings=settings,
        now=CALENDAR_NOW,
    )
    return agent, provider


def intake_all(settings: Settings | None = None) -> list[IntakeResult]:
    """Process every fixture transcript."""
    settings = settings or Settings.from_env()
    booking_agent, _ = build_booking_agent(settings)

    return [
        CallIntakeAgent(
            provider=provider_for(transcript.id),
            booking_agent=booking_agent,
            settings=settings,
        ).intake(transcript)
        for transcript in TRANSCRIPTS
    ]


def _print(result: IntakeResult) -> None:
    e = result.extraction
    print(f"\n{'=' * 74}")
    print(
        f"{result.transcript_id}  |  {e.intent.value} / {e.urgency.value} "
        f"/ confidence {e.confidence:.2f}"
    )
    print("=" * 74)
    print(f"  {e.summary}")

    c = e.contact
    unverified = {issue.field for issue in result.grounding_issues}
    print("\n  contact:")
    for label, value in (
        ("name", c.name),
        ("company", c.company),
        ("email", c.email),
        ("phone", c.phone),
    ):
        if value is None:
            print(f"    {label:<8} -")
        elif label in unverified:
            print(f"    {label:<8} {value}   <-- NOT SAID BY THE CALLER")
        else:
            print(f"    {label:<8} {value}")

    if result.proposal is not None:
        print("\n  delegated to calendar-booking:")
        if result.proposal.has_options:
            for index, slot in enumerate(result.proposal.slots, 1):
                print(f"    {index}. {slot.local('Europe/Berlin')}")
        else:
            print("    no openings found")

    if result.requires_human:
        print("\n  route: -> HUMAN")
        for reason in result.escalation_reasons:
            print(f"    ! {reason}")
    else:
        print("\n  route: CLEARED")

    print(f"  cost: ${result.cost_usd:.6f}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("call-intake demo")
    print(f"mode={settings.mode}  model={settings.model}  calls={len(TRANSCRIPTS)}")

    results = intake_all(settings)
    for result in results:
        _print(result)

    escalated = sum(1 for r in results if r.requires_human)
    hallucinated = sum(1 for r in results if r.grounding_issues)
    booked = sum(1 for r in results if r.proposal is not None)

    print(f"\n{'=' * 74}")
    print(
        f"{len(results)} calls | {escalated} to a human | {hallucinated} with "
        f"unverifiable details | {booked} sent to the booking agent"
    )
    print(
        "Contact details are checked back against what the caller actually said,\n"
        "and the transcript is treated as data throughout — see extraction.py."
    )


if __name__ == "__main__":
    main()
