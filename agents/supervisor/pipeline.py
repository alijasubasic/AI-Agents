"""Running every agent together.

This is the part that makes the repository a system rather than four separate
demonstrations. One function drives all four specialists over their fixtures,
adapts every outcome into a `Decision`, and hands the lot to the supervisor.

The order is not arbitrary. `call-intake` already delegates to
`calendar-booking`, so calls are processed before standalone bookings; and
`lead-research` runs before the outreach draft that quotes it, because the
draft's claims are only checkable against a profile that has already been
verified.
"""

from __future__ import annotations

from agents.calendar_booking.agent import CalendarBookingAgent
from agents.calendar_booking.fixtures import ORGANISER
from agents.calendar_booking.fixtures import REFERENCE_NOW as CALENDAR_NOW
from agents.calendar_booking.providers import MockCalendar
from agents.call_intake.agent import CallIntakeAgent
from agents.call_intake.fixtures import TRANSCRIPTS
from agents.call_intake.scripted import provider_for as intake_provider
from agents.email_triage.agent import EmailTriageAgent
from agents.email_triage.fixtures import INBOX
from agents.email_triage.providers import MockCrm, MockMailbox
from agents.email_triage.scripted import provider_for as triage_provider
from agents.lead_research.agent import LeadResearchAgent
from agents.lead_research.fixtures import REFERENCE_TODAY
from agents.lead_research.providers import MockSearch
from agents.lead_research.scripted import provider_for as research_provider
from agents.supervisor.collect import (
    follow_up_from_intake,
    from_intake,
    from_research,
    from_triage,
    outreach_from_research,
)
from agents.supervisor.models import Decision
from agents.supervisor.scripted import FOLLOW_UP_DRAFTS, OUTREACH_DRAFTS
from core.config import Settings
from core.llm import MockProvider, text_response

#: Companies the research agent covers in a full run.
RESEARCH_TARGETS = ("Kestrel Systems", "Halvard Marine")


def run_email_triage(settings: Settings) -> list[Decision]:
    """Triage the whole fixture inbox."""
    mailbox = MockMailbox()
    decisions: list[Decision] = []

    for email in INBOX:
        agent = EmailTriageAgent(
            provider=triage_provider(email.id),
            crm=MockCrm(),
            mailbox=mailbox,
            settings=settings,
        )
        result = agent.triage(email)
        decisions.append(from_triage(result, email, sent=agent.send_if_allowed(result)))

    return decisions


def run_call_intake(settings: Settings) -> list[Decision]:
    """Process every call, letting intake delegate to the booking agent."""
    booking = CalendarBookingAgent(
        # Never consulted: delegation goes through propose_for(), which runs
        # the scheduling engine and calls no model. See ADR 0004.
        provider=MockProvider([text_response("{}")], model="claude-opus-5"),
        calendar=MockCalendar(),
        organiser=ORGANISER,
        settings=settings,
        now=CALENDAR_NOW,
    )

    decisions: list[Decision] = []
    for transcript in TRANSCRIPTS:
        result = CallIntakeAgent(
            provider=intake_provider(transcript.id),
            booking_agent=booking,
            settings=settings,
        ).intake(transcript)
        decisions.append(from_intake(result))

        # Where a follow-up was drafted, whether it may be sent is a separate
        # decision from what the call was about, and gets reviewed separately.
        draft = FOLLOW_UP_DRAFTS.get(transcript.id)
        if draft is not None:
            decisions.append(follow_up_from_intake(result, draft))

    return decisions


def run_lead_research(settings: Settings) -> list[Decision]:
    """Research each target, then draft the outreach that quotes it.

    The outreach draft is where the chain closes: research labelled some claims
    unsupported, and the draft repeats one of them. Nothing here notices — the
    codex does, later.
    """
    decisions: list[Decision] = []

    for company in RESEARCH_TARGETS:
        result = LeadResearchAgent(
            provider=research_provider(company),
            search=MockSearch(),
            settings=settings,
            today=REFERENCE_TODAY,
        ).research(company)

        decisions.append(from_research(result))

        draft = OUTREACH_DRAFTS.get(company)
        if draft is not None:
            decisions.append(
                outreach_from_research(
                    result,
                    draft["body"],
                    recipient=draft["recipient"],
                    recipient_verified=draft["recipient_verified"],
                )
            )

    return decisions


def run_all(settings: Settings | None = None) -> list[Decision]:
    """Drive every agent and return everything they decided."""
    settings = settings or Settings.from_env()
    return [
        *run_email_triage(settings),
        *run_call_intake(settings),
        *run_lead_research(settings),
    ]
