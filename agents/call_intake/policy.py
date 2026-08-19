"""Escalation policy for call intake.

Same principle as the triage agent: the model reports what it heard, and
deterministic rules decide what a person has to deal with. The rules here are
stricter, because a phone call gives the caller a live channel to say anything
at all and there is no thread history to check it against.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agents.call_intake.models import (
    CallIntent,
    ExtractedCall,
    GroundingIssue,
    Urgency,
)


class IntakePolicy(BaseModel):
    """When a call must reach a human."""

    #: Deliberately below the email agent's 0.75. Transcripts carry noise that
    #: written mail does not — inaudible passages, half sentences, crosstalk —
    #: so honest confidence scores genuinely run lower here. Holding the same
    #: bar would escalate nearly every call and turn the signal into wallpaper.
    #: The grounding check is what compensates: it catches invented detail
    #: regardless of how confident the model felt.
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    always_escalate_intents: frozenset[CallIntent] = Field(
        default=frozenset({CallIntent.COMPLAINT})
    )

    always_escalate_urgency: frozenset[Urgency] = Field(default=frozenset({Urgency.IMMEDIATE}))

    #: An extracted detail the caller never said means the model filled a gap.
    #: Whatever else is true of that extraction, a person should see it.
    escalate_on_grounding_issue: bool = True

    #: An instruction-override attempt is never handled automatically.
    escalate_on_injection: bool = True

    #: A caller who wants a follow-up but left no way to reach them needs a
    #: human to work out what to do — there is nothing to automate.
    escalate_when_unreachable: bool = True

    model_config = {"frozen": True}

    def evaluate(
        self,
        extraction: ExtractedCall,
        *,
        grounding_issues: list[GroundingIssue] | None = None,
        injection_signals: list[str] | None = None,
    ) -> list[str]:
        """Return every reason this call needs a person. Empty means it does not."""
        reasons: list[str] = []
        grounding_issues = grounding_issues or []
        injection_signals = injection_signals or []

        if self.escalate_on_injection and injection_signals:
            reasons.extend(f"possible prompt injection: {signal}" for signal in injection_signals)

        if self.escalate_on_grounding_issue:
            reasons.extend(
                f"unverified {issue.field}: {issue.reason}" for issue in grounding_issues
            )

        if extraction.confidence < self.min_confidence:
            reasons.append(
                f"low confidence ({extraction.confidence:.2f} < {self.min_confidence:.2f})"
            )

        if extraction.intent in self.always_escalate_intents:
            reasons.append(f"intent is {extraction.intent.value}")

        if extraction.urgency in self.always_escalate_urgency:
            reasons.append(f"urgency is {extraction.urgency.value}")

        if (
            self.escalate_when_unreachable
            and extraction.follow_up_actions
            and not extraction.contact.is_reachable
        ):
            reasons.append("follow-up requested but no contact details were given")

        return reasons

    def may_book(
        self,
        extraction: ExtractedCall,
        *,
        injection_signals: list[str] | None = None,
    ) -> bool:
        """Whether the booking agent may be consulted for this call.

        Separate from escalation on purpose. A call can be flagged for review
        and still be worth preparing options for — but a call carrying an
        injection attempt gets nothing done on its behalf at all.
        """
        if injection_signals and self.escalate_on_injection:
            return False
        return extraction.wants_meeting and extraction.intent is not CallIntent.SPAM


DEFAULT_POLICY = IntakePolicy()
