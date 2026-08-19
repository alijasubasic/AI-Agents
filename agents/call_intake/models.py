"""Data models for call intake.

A transcript is the least trustworthy input in this repository. It is free text
produced by a stranger, transcribed imperfectly, and fed straight into a model
that is then asked to act on it. Two consequences shape these models:

* Contact details are `None` when the caller did not state them. There is no
  "best guess" — an invented phone number is worse than a missing one.
* What the model extracted is kept separate from what was *verified* against
  the transcript, so the two can be compared rather than conflated.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from agents.calendar_booking.models import BookingResult, MeetingProposal


class CallIntent(StrEnum):
    """What the caller rang about."""

    NEW_ENQUIRY = "new_enquiry"
    SUPPORT = "support"
    COMPLAINT = "complaint"
    SCHEDULING = "scheduling"
    BILLING = "billing"
    SPAM = "spam"
    OTHER = "other"


class Urgency(StrEnum):
    IMMEDIATE = "immediate"
    SAME_DAY = "same_day"
    THIS_WEEK = "this_week"
    WHENEVER = "whenever"


class Turn(BaseModel):
    """One utterance in the call."""

    speaker: Literal["caller", "agent"]
    text: str


class CallTranscript(BaseModel):
    """A transcribed phone call."""

    id: str
    received_at: datetime
    duration_seconds: int = 0
    turns: list[Turn] = Field(default_factory=list)

    @property
    def text(self) -> str:
        """The whole call as plain text, speaker-labelled."""
        return "\n".join(f"{turn.speaker}: {turn.text}" for turn in self.turns)

    @property
    def caller_text(self) -> str:
        """Only what the caller said.

        Grounding checks run against this rather than the whole transcript: a
        detail our own operator read aloud is not the caller confirming it.
        """
        return "\n".join(turn.text for turn in self.turns if turn.speaker == "caller")


class ContactDetails(BaseModel):
    """Who called. Every field is optional on purpose.

    Field descriptions are prompt text — this schema is what the model is shown.
    """

    name: str | None = Field(
        default=None, description="Caller's full name, or null if they never gave it."
    )
    company: str | None = Field(default=None, description="Company name, or null if not mentioned.")
    email: str | None = Field(
        default=None,
        description=(
            "Email address exactly as the caller spelled it out, or null. "
            "Never reconstruct an address from a name and a company domain."
        ),
    )
    phone: str | None = Field(
        default=None,
        description="Callback number exactly as stated, or null if not given.",
    )

    @property
    def is_reachable(self) -> bool:
        return bool(self.email or self.phone)


class ExtractedCall(BaseModel):
    """What the model made of the call."""

    intent: CallIntent = Field(description="The caller's primary reason for ringing.")
    urgency: Urgency = Field(description="How soon the caller needs a response.")
    summary: str = Field(description="Two or three sentences on what the caller wants.")
    contact: ContactDetails
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in this extraction, 0 to 1. Transcription errors and "
            "half-finished sentences should lower it. A low score routes the "
            "call to a human, which is the correct outcome when the call was "
            "unclear."
        ),
    )
    wants_meeting: bool = Field(
        default=False,
        description="True only if the caller explicitly asked to arrange a meeting or call back.",
    )
    meeting_topic: str = Field(
        default="", description="What the meeting would be about. Empty if none was requested."
    )
    follow_up_actions: list[str] = Field(
        default_factory=list,
        description="Concrete things the caller asked for. Empty if none.",
    )


class GroundingIssue(BaseModel):
    """A detail the model reported that the transcript does not support."""

    field: str
    value: str
    reason: str


class IntakeResult(BaseModel):
    """Everything the intake produced for one call."""

    transcript_id: str
    extraction: ExtractedCall

    #: Extracted details that could not be found in what the caller actually said.
    grounding_issues: list[GroundingIssue] = Field(default_factory=list)

    #: Set when the call asked for a meeting and the booking agent was consulted.
    proposal: MeetingProposal | None = None
    booking: BookingResult | None = None

    requires_human: bool = False
    escalation_reasons: list[str] = Field(default_factory=list)
    summary_markdown: str = ""

    cost_usd: float = 0.0
    duration_ms: float = 0.0

    @property
    def is_clean(self) -> bool:
        """True when nothing needs a person and nothing was invented."""
        return not self.requires_human and not self.grounding_issues
