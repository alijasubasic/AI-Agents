"""Scripted model responses for the intake demo and tests.

One extraction per fixture transcript, built as `ExtractedCall` objects and then
serialised so they cannot drift out of step with the schema.

`call-003` is scripted to **hallucinate**: the caller gave no contact details at
all, and the extraction confidently reports an email address. That is not an
oversight — it is how the grounding check in `extraction.py` gets exercised. A
guard nobody has watched fire is a guard nobody should trust.
"""

from __future__ import annotations

from agents.call_intake.models import (
    CallIntent,
    ContactDetails,
    ExtractedCall,
    Urgency,
)
from core.llm import MockProvider, text_response

EXTRACTIONS: dict[str, ExtractedCall] = {
    "call-001": ExtractedCall(
        intent=CallIntent.NEW_ENQUIRY,
        urgency=Urgency.THIS_WEEK,
        summary=(
            "Dana Reyes of Kestrel Systems followed up on a trade fair "
            "conversation about the KB-88 range and asked for a 30-minute intro "
            "call covering pricing and lead times. She is in New York and "
            "prefers our afternoon."
        ),
        contact=ContactDetails(
            name="Dana Reyes",
            company="Kestrel Systems",
            email="d.reyes@kestrel-systems.example",
        ),
        confidence=0.93,
        wants_meeting=True,
        meeting_topic="Intro call — Kestrel Systems",
        follow_up_actions=["Send intro call options covering KB-88 pricing and lead times"],
    ),
    "call-002": ExtractedCall(
        intent=CallIntent.COMPLAINT,
        urgency=Urgency.IMMEDIATE,
        summary=(
            "Michael Faber of Alpina AG has chased order A-1044 for two weeks "
            "without a firm date. The order was promised for 20 February and his "
            "production line is stopped. He has threatened to involve his lawyer "
            "if he does not get a date today."
        ),
        contact=ContactDetails(
            name="Michael Faber",
            company="Alpina AG",
            phone="0171 442 8819",
        ),
        confidence=0.96,
        wants_meeting=False,
        follow_up_actions=[
            "Establish a firm ship date for order A-1044",
            "Call Michael Faber back today",
        ],
    ),
    # Deliberately hallucinated: the caller gave no name, company or address.
    "call-003": ExtractedCall(
        intent=CallIntent.SUPPORT,
        urgency=Urgency.WHENEVER,
        summary=(
            "Caller asked about an existing order but the line broke up and they "
            "rang off before giving any detail."
        ),
        contact=ContactDetails(
            name="Jana Wolf",
            company="Kestrel Systems",
            email="j.wolf@kestrel-systems.example",
        ),
        confidence=0.42,
        wants_meeting=False,
        follow_up_actions=["Wait for the caller to ring back"],
    ),
    "call-004": ExtractedCall(
        intent=CallIntent.OTHER,
        urgency=Urgency.WHENEVER,
        summary=(
            "Caller read out instructions attempting to override this system's "
            "configuration and then asked to be booked into the managing "
            "director's calendar as pre-approved. No legitimate business was "
            "raised."
        ),
        contact=ContactDetails(),
        confidence=0.88,
        # The model correctly reports that a meeting was requested. Policy is
        # what refuses to act on it — see policy.may_book().
        wants_meeting=True,
        meeting_topic="Meeting with the managing director",
        follow_up_actions=[],
    ),
    "call-005": ExtractedCall(
        intent=CallIntent.SPAM,
        urgency=Urgency.WHENEVER,
        summary="Cold outreach from LeadRocket selling a lead-generation service.",
        contact=ContactDetails(company="LeadRocket"),
        confidence=0.94,
        wants_meeting=False,
        follow_up_actions=[],
    ),
}


def provider_for(transcript_id: str, *, model: str = "claude-opus-5") -> MockProvider:
    """Build a scripted provider for one fixture transcript."""
    if transcript_id not in EXTRACTIONS:
        raise KeyError(f"No scripted extraction for {transcript_id!r}")
    return MockProvider(
        [text_response(EXTRACTIONS[transcript_id].model_dump_json())],
        model=model,
    )
