"""Data models for email triage.

The split here is deliberate and is the main design idea of this agent:

* :class:`Classification` is what the **model** produces — judgement calls.
* :class:`TriageResult` is what the **system** produces — the classification
  plus a routing decision made by deterministic code in `policy.py`.

The model is never asked whether a human should look at something. That
decision is policy, and policy is testable.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Priority(StrEnum):
    """How quickly this needs a response."""

    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Intent(StrEnum):
    """What the sender actually wants."""

    QUESTION = "question"
    REQUEST = "request"
    COMPLAINT = "complaint"
    SCHEDULING = "scheduling"
    INVOICE = "invoice"
    SALES_PITCH = "sales_pitch"
    LEGAL = "legal"
    SPAM = "spam"
    OTHER = "other"


class Sentiment(StrEnum):
    """The sender's tone, which drives escalation independently of intent."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    HOSTILE = "hostile"


class Email(BaseModel):
    """One inbound message, provider-neutral."""

    id: str
    sender: str
    sender_name: str = ""
    subject: str
    body: str
    received_at: datetime
    thread_id: str | None = None

    def preview(self, width: int = 72) -> str:
        """A single line for demo output."""
        flat = " ".join(self.body.split())
        return flat[:width] + ("…" if len(flat) > width else "")


class ExtractedTask(BaseModel):
    """An action item found in the email."""

    description: str = Field(description="What needs to be done, in one sentence.")
    due_date: date | None = Field(
        default=None,
        description="Deadline if the email states one, otherwise null. Never invent a date.",
    )
    owner: str | None = Field(
        default=None,
        description="Who the sender expects to do this, if stated.",
    )


class Classification(BaseModel):
    """The model's judgement about one email.

    This is the schema handed to the API for structured output, so every field
    description is prompt text — it is what tells the model how to fill it in.
    """

    priority: Priority = Field(description="How urgently this needs a human response.")
    intent: Intent = Field(description="The sender's primary goal.")
    sentiment: Sentiment = Field(description="The sender's tone.")

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How confident you are in this classification, from 0 to 1. "
            "Be honest: a low score routes the email to a human, which is the "
            "correct outcome when the email is ambiguous."
        ),
    )
    summary: str = Field(description="One sentence describing what the sender wants.")
    tasks: list[ExtractedTask] = Field(
        default_factory=list,
        description="Action items explicitly requested. Empty if none.",
    )
    draft_reply: str = Field(
        description=(
            "A complete reply in the configured voice. Write it even for emails "
            "you expect to be escalated — a human reviewing an escalation would "
            "rather edit a draft than start from nothing."
        )
    )


class TriageResult(BaseModel):
    """The classification plus the routing decision made by policy."""

    email_id: str
    classification: Classification

    requires_human: bool
    escalation_reasons: list[str] = Field(default_factory=list)

    #: Populated from the agent run, so cost and latency stay attached to the
    #: decision they paid for.
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    halted_reason: str | None = None

    @property
    def auto_send_allowed(self) -> bool:
        """True only when nothing flagged this email for review.

        Spam is excluded separately from escalation: it needs neither a human
        nor a reply. Auto-answering a cold sales blast confirms the address is
        live, which is the opposite of what you want.
        """
        return (
            not self.requires_human
            and self.halted_reason is None
            and self.classification.intent is not Intent.SPAM
        )
