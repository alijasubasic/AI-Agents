"""Escalation policy.

Deciding whether a human must look at an email is *not* a job for the model.
A language model asked "should a human review this?" will answer differently
on different days, and its answer cannot be unit-tested.

So the model classifies, and this module decides. Every rule here is
deterministic, has a stated reason, and is covered by a test.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agents.email_triage.models import (
    Classification,
    Intent,
    Priority,
    Sentiment,
)

#: Phrases that force human review regardless of how the model classified the
#: email. Deliberately blunt: a false escalation costs a minute of someone's
#: time, while a missed legal threat costs considerably more.
SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(lawyer|attorney|solicitor|legal action|sue|lawsuit|court)\b", "legal language"),
    (r"\b(gdpr|data protection|privacy complaint|dsgvo)\b", "data protection matter"),
    (
        r"\b(cancel|terminate|churn)\w*\s+(our|my|the)\s+(contract|subscription|account)\b",
        "contract termination",
    ),
    (r"\b(refund|chargeback|compensation)\b", "money leaving the business"),
    (r"\b(press|journalist|reporter|twitter|linkedin post)\b", "public exposure risk"),
)


class EscalationPolicy(BaseModel):
    """Rules deciding when a human must review before anything is sent."""

    #: Below this confidence, the model is guessing and a human decides.
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)

    #: Intents that always get a human, however confident the model is.
    always_escalate_intents: frozenset[Intent] = Field(
        default=frozenset({Intent.COMPLAINT, Intent.LEGAL})
    )

    #: Sentiments that always get a human.
    always_escalate_sentiments: frozenset[Sentiment] = Field(default=frozenset({Sentiment.HOSTILE}))

    #: Urgent mail is answered by a person, not a draft.
    escalate_urgent: bool = True

    #: Scan the raw body for sensitive phrases the classifier may have missed.
    scan_body: bool = True

    model_config = {"frozen": True}

    def evaluate(self, classification: Classification, body: str = "") -> list[str]:
        """Return the reasons this email needs a human. Empty means auto-send is fine.

        Reasons accumulate rather than short-circuiting: when a human opens an
        escalation they should see every rule that fired, not just the first.
        """
        reasons: list[str] = []

        if classification.confidence < self.min_confidence:
            reasons.append(
                f"low confidence ({classification.confidence:.2f} < {self.min_confidence:.2f})"
            )

        if classification.intent in self.always_escalate_intents:
            reasons.append(f"intent is {classification.intent.value}")

        if classification.sentiment in self.always_escalate_sentiments:
            reasons.append(f"sentiment is {classification.sentiment.value}")

        if self.escalate_urgent and classification.priority is Priority.URGENT:
            reasons.append("priority is urgent")

        if self.scan_body and body:
            reasons.extend(
                f"body mentions {label}"
                for pattern, label in SENSITIVE_PATTERNS
                if re.search(pattern, body, re.IGNORECASE)
            )

        return reasons

    def requires_human(self, classification: Classification, body: str = "") -> bool:
        return bool(self.evaluate(classification, body))


#: The policy used unless a caller supplies its own.
DEFAULT_POLICY = EscalationPolicy()
