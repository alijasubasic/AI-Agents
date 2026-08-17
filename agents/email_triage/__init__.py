"""Email triage: classify inbound mail, extract tasks, draft replies, escalate.

The model classifies. Deterministic policy decides what a human must see.
"""

from agents.email_triage.agent import EmailTriageAgent, build_tools
from agents.email_triage.models import (
    Classification,
    Email,
    ExtractedTask,
    Intent,
    Priority,
    Sentiment,
    TriageResult,
)
from agents.email_triage.policy import DEFAULT_POLICY, EscalationPolicy
from agents.email_triage.providers import (
    Account,
    CrmProvider,
    GmailMailbox,
    HttpCrm,
    MailboxProvider,
    MockCrm,
    MockMailbox,
)

__all__ = [
    "DEFAULT_POLICY",
    "Account",
    "Classification",
    "CrmProvider",
    "Email",
    "EmailTriageAgent",
    "EscalationPolicy",
    "ExtractedTask",
    "GmailMailbox",
    "HttpCrm",
    "Intent",
    "MailboxProvider",
    "MockCrm",
    "MockMailbox",
    "Priority",
    "Sentiment",
    "TriageResult",
    "build_tools",
]
