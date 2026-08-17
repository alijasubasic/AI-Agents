"""Scripted model responses for the fixture inbox.

Shared by the demo and the test suite so both exercise identical behaviour. The
classifications are built as :class:`Classification` objects and then
serialised, rather than written as JSON by hand — a hand-written fixture can
drift out of step with the schema, a constructed one cannot.
"""

from __future__ import annotations

from datetime import date

from agents.email_triage.models import (
    Classification,
    ExtractedTask,
    Intent,
    Priority,
    Sentiment,
)
from core.llm import MockProvider, text_response, tool_response

#: What a well-behaved model would return for each fixture email.
CLASSIFICATIONS: dict[str, Classification] = {
    "msg-001": Classification(
        priority=Priority.NORMAL,
        intent=Intent.QUESTION,
        sentiment=Sentiment.NEUTRAL,
        confidence=0.92,
        summary="Asks for volume pricing on 200 units of KB-88 and the current lead time.",
        tasks=[
            ExtractedTask(description="Quote volume pricing for 200 units of KB-88"),
            ExtractedTask(description="Confirm current lead time for KB-88"),
        ],
        draft_reply=(
            "Hi Petra,\n\n"
            "Thanks for the enquiry. We do offer volume pricing at 200 units, but "
            "I don't want to quote a figure before sales has confirmed the Q2 "
            "tier — I'll have that to you by Thursday.\n\n"
            "On lead time: I can't give you a reliable number without checking "
            "current production capacity, so I'll include it in the same reply "
            "rather than guess now.\n\n"
            "Best,\nAlija"
        ),
    ),
    "msg-002": Classification(
        priority=Priority.URGENT,
        intent=Intent.COMPLAINT,
        sentiment=Sentiment.HOSTILE,
        confidence=0.95,
        summary=(
            "Third complaint about delayed order A-1044; threatens legal "
            "action and public escalation."
        ),
        tasks=[
            ExtractedTask(
                description="Establish and communicate a firm ship date for order A-1044",
                due_date=date(2026, 3, 6),
            ),
            ExtractedTask(description="Have someone call Michael Faber directly today"),
        ],
        draft_reply=(
            "Mr Faber,\n\n"
            "You're right to be angry — three emails without a straight answer is "
            "not acceptable, and the February 20th date should not have been "
            "given if we couldn't hold it.\n\n"
            "I'm not going to give you a fourth estimate I can't stand behind. "
            "I've escalated A-1044 internally and someone with authority over "
            "the production schedule will call you today with a date and what "
            "we're doing about the delay.\n\n"
            "Alija"
        ),
    ),
    "msg-003": Classification(
        priority=Priority.HIGH,
        intent=Intent.INVOICE,
        sentiment=Sentiment.NEUTRAL,
        confidence=0.88,
        summary="Suspects invoice 2026-0412 duplicates already-paid invoice 2026-0397.",
        tasks=[
            ExtractedTask(
                description="Check whether invoice 2026-0412 duplicates 2026-0397",
            ),
            ExtractedTask(description="Issue a refund or credit note if it is a duplicate"),
        ],
        draft_reply=(
            "Good morning Ms Kruse,\n\n"
            "Thanks for flagging this. Two invoices for one delivery does look "
            "like a duplicate, but I'd rather check the records than confirm it "
            "from the description alone.\n\n"
            "Accounts will review 2026-0412 against 2026-0397 and come back to "
            "you by Tuesday with either a credit note or an explanation of what "
            "the second invoice covers.\n\n"
            "Kind regards,\nAlija"
        ),
    ),
    "msg-004": Classification(
        priority=Priority.NORMAL,
        intent=Intent.SCHEDULING,
        sentiment=Sentiment.POSITIVE,
        confidence=0.90,
        summary="Wants a 30-minute intro call next week, Tuesday or Thursday afternoon CET.",
        tasks=[
            ExtractedTask(
                description="Book a 30-minute call with Tobias Berger, Tue or Thu afternoon CET",
            )
        ],
        draft_reply=(
            "Hi Tobias,\n\n"
            "Good to hear from you after the fair. Thursday afternoon works — "
            "I'll send an invite for 15:00 CET, 30 minutes.\n\n"
            "If Tuesday turns out to suit you better, say so and I'll move it.\n\n"
            "Best,\nAlija"
        ),
    ),
    "msg-005": Classification(
        priority=Priority.LOW,
        intent=Intent.SPAM,
        sentiment=Sentiment.NEUTRAL,
        confidence=0.97,
        summary="Unsolicited cold outreach for a lead-generation product.",
        tasks=[],
        draft_reply="",
    ),
    "msg-006": Classification(
        priority=Priority.NORMAL,
        intent=Intent.REQUEST,
        sentiment=Sentiment.NEUTRAL,
        confidence=0.35,
        summary=(
            "Asks for something to be sent over, but never says what. No context "
            "in the message and no prior thread to resolve it."
        ),
        tasks=[ExtractedTask(description="Identify what Jana Wolf is asking to be sent")],
        draft_reply=(
            "Hi Jana,\n\n"
            "Happy to send it — I just want to make sure I send the right thing. "
            "Which document do you mean?\n\n"
            "Best,\nAlija"
        ),
    ),
}

#: Sender domains the model looks up before classifying.
_DOMAINS: dict[str, str] = {
    "msg-001": "nordwind-logistik.example",
    "msg-002": "alpina-ag.example",
    "msg-003": "sudwest-handel.example",
    "msg-004": "meridian-consulting.example",
    "msg-006": "kestrel-systems.example",
}


def provider_for(email_id: str, *, model: str = "claude-opus-5") -> MockProvider:
    """Build a scripted provider for one fixture email.

    Most emails script a CRM lookup followed by the classification. Spam skips
    the lookup, which is also what a sensible model would do.
    """
    if email_id not in CLASSIFICATIONS:
        raise KeyError(f"No scripted classification for {email_id!r}")

    responses = []
    if email_id in _DOMAINS:
        responses.append(
            tool_response(
                "lookup_sender_account",
                {"domain": _DOMAINS[email_id]},
                call_id=f"{email_id}-crm",
            )
        )
    responses.append(text_response(CLASSIFICATIONS[email_id].model_dump_json()))
    return MockProvider(responses, model=model)
