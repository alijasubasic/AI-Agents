"""Scripted model responses for the booking demo and tests.

The proposal messages here deliberately do **not** hard-code clock times. The
authoritative times come from the scheduling engine, and a fixture that also
spelled them out would be a second source of truth waiting to disagree with the
first. The engine's slots are what the demo prints.
"""

from __future__ import annotations

from agents.calendar_booking.models import BookingRequest, ProposalDraft
from core.llm import MockProvider, text_response, tool_response

NINA = "n.brandt@example.com"
DANA = "d.reyes@kestrel-systems.example"
TOBIAS = "t.berger@meridian-consulting.example"


DRAFTS: dict[str, ProposalDraft] = {
    "internal": ProposalDraft(
        request=BookingRequest(
            title="Supplier review follow-up",
            duration_minutes=45,
            attendee_emails=[NINA],
            notes="Follow-up to Friday's supplier review.",
        ),
        message=(
            "Hi Nina,\n\n"
            "Here are the openings we both have for the supplier review "
            "follow-up — 45 minutes. Take whichever suits you and I'll send the "
            "invite.\n\n"
            "Alija"
        ),
    ),
    "transatlantic": ProposalDraft(
        request=BookingRequest(
            title="Intro call — Kestrel Systems",
            duration_minutes=30,
            attendee_emails=[DANA],
            notes="Dana is in New York; only the afternoon overlaps with Berlin.",
        ),
        message=(
            "Hi Dana,\n\n"
            "These are the slots that fall inside working hours on both sides. "
            "Times are shown in Berlin and New York — let me know which works "
            "and I'll book it.\n\n"
            "Alija"
        ),
    ),
    "impossible": ProposalDraft(
        request=BookingRequest(
            title="Contract walkthrough",
            duration_minutes=30,
            attendee_emails=[TOBIAS],
            earliest_date="2026-03-11",
            latest_date="2026-03-11",
            notes="Requester insisted on Wednesday the 11th.",
        ),
        message="(replaced by the deterministic no-options message)",
    ),
}


_TOOL_ARGS: dict[str, dict] = {
    "internal": {"attendee_emails": [NINA], "duration_minutes": 45},
    "transatlantic": {"attendee_emails": [DANA], "duration_minutes": 30},
    "impossible": {
        "attendee_emails": [TOBIAS],
        "duration_minutes": 30,
        "earliest_date": "2026-03-11",
        "latest_date": "2026-03-11",
    },
}


REQUESTS: dict[str, str] = {
    "internal": (
        "Can you find 45 minutes with Nina next week so we can go through what "
        "came out of the supplier review?"
    ),
    "transatlantic": (
        "I need a 30 minute intro call with Dana Reyes at Kestrel Systems. She's based in New York."
    ),
    "impossible": (
        "Set up 30 minutes with Tobias Berger for the contract walkthrough. "
        "It has to be Wednesday the 11th."
    ),
}


def provider_for(scenario: str, *, model: str = "claude-opus-5") -> MockProvider:
    """Build a scripted provider for one demo scenario."""
    if scenario not in DRAFTS:
        raise KeyError(f"No scripted scenario {scenario!r}")

    return MockProvider(
        [
            tool_response(
                "find_available_slots",
                _TOOL_ARGS[scenario],
                call_id=f"{scenario}-slots",
            ),
            text_response(DRAFTS[scenario].model_dump_json()),
        ],
        model=model,
    )
