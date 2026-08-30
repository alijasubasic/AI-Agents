"""Outreach: one short first-contact email per business, and every reason not to send it.

The model writes the text. Deterministic code writes the footer, decides who may
be written to, and counts how often. Sending needs three separate yesses.
"""

from agents.outreach.agent import OutreachAgent, candidate_address
from agents.outreach.models import (
    Campaign,
    Language,
    OutreachEmail,
    OutreachResult,
    Sender,
    render_message,
)
from agents.outreach.policy import DEFAULT_POLICY, OutreachPolicy, unbacked_claims
from agents.outreach.providers import MailSender, MockSender, OutboundMessage, SmtpSender
from agents.outreach.suppression import (
    FileSuppressionList,
    MemorySuppressionList,
    SuppressionEntry,
    SuppressionProvider,
)

__all__ = [
    "DEFAULT_POLICY",
    "Campaign",
    "FileSuppressionList",
    "Language",
    "MailSender",
    "MemorySuppressionList",
    "MockSender",
    "OutboundMessage",
    "OutreachAgent",
    "OutreachEmail",
    "OutreachPolicy",
    "OutreachResult",
    "Sender",
    "SmtpSender",
    "SuppressionEntry",
    "SuppressionProvider",
    "candidate_address",
    "render_message",
    "unbacked_claims",
]
