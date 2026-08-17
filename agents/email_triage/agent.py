"""The email triage agent.

Flow for one email:

    1. The model classifies it and drafts a reply, using CRM tools if it needs
       context about the sender.
    2. `policy.py` decides — in plain deterministic code — whether a human must
       review before anything is sent.
    3. The result carries both, plus what the run cost.

Step 2 is the part worth looking at. The model is never asked "should a human
see this?", because that answer has to be the same every time.
"""

from __future__ import annotations

from agents.email_triage.fixtures import VOICE_GUIDE
from agents.email_triage.models import Classification, Email, TriageResult
from agents.email_triage.policy import DEFAULT_POLICY, EscalationPolicy
from agents.email_triage.providers import CrmProvider, MailboxProvider
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider
from core.models import RunResult
from core.tools import Tool, ToolRegistry

SYSTEM_PROMPT = """\
You triage inbound business email for a hardware distributor.

For each email you receive, produce a classification: how urgent it is, what
the sender wants, their tone, how confident you are, any action items, and a
draft reply.

Rules:

- Use the CRM tools before judging priority. A key account with a delayed order
  is not the same as a first-time enquiry, and you cannot tell them apart from
  the email alone.
- Extract only tasks the sender actually asked for. Do not invent follow-ups.
- Never state a price, date, stock level, or commitment that is not present in
  the email or in a tool result. If you do not know, the draft says so.
- Report confidence honestly. A vague email with no context should score low.
  Low confidence sends the email to a human, which is the right outcome — it is
  not a failure you should avoid by guessing.
- Write the draft reply in the voice described below, even when you expect the
  email to be escalated. A human reviewing it would rather edit than start cold.

VOICE:
{voice}
"""

EMAIL_TEMPLATE = """\
Classify this email.

From: {sender_name} <{sender}>
Subject: {subject}
Received: {received_at:%Y-%m-%d %H:%M} UTC

---
{body}
---
"""


def build_tools(crm: CrmProvider) -> ToolRegistry:
    """Build the tool set, closing over the CRM implementation in use.

    Tools are constructed per-agent rather than declared at module level so the
    mock and the real CRM go through exactly the same code path.
    """

    def lookup_sender_account(domain: str) -> str:
        """Look up the CRM account for an email sender's domain.

        Args:
            domain: The domain part of the sender address, e.g. "alpina-ag.example".
        """
        account = crm.lookup_account(domain)
        if account is None:
            return f"No CRM account found for {domain}. Treat as a new contact."
        return (
            f"{account.company} | tier: {account.tier} | "
            f"lifetime value: EUR {account.lifetime_value_eur:,} | "
            f"open orders: {', '.join(account.open_orders) or 'none'} | "
            f"notes: {account.notes or 'none'}"
        )

    return ToolRegistry([Tool(lookup_sender_account)])


class EmailTriageAgent:
    """Classifies inbound email and decides what a human needs to see."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        crm: CrmProvider,
        mailbox: MailboxProvider | None = None,
        policy: EscalationPolicy = DEFAULT_POLICY,
        voice: str = VOICE_GUIDE,
        settings: Settings | None = None,
    ) -> None:
        self.mailbox = mailbox
        self.policy = policy
        self._agent = Agent(
            name="email-triage",
            system_prompt=SYSTEM_PROMPT.format(voice=voice.strip()),
            provider=provider,
            tools=build_tools(crm),
            settings=settings,
        )

    def triage(self, email: Email) -> TriageResult:
        """Classify one email and apply the escalation policy."""
        prompt = EMAIL_TEMPLATE.format(
            sender_name=email.sender_name or email.sender,
            sender=email.sender,
            subject=email.subject,
            received_at=email.received_at,
            body=email.body,
        )
        classification, run = self._agent.run_structured(prompt, Classification)
        return self._decide(email, classification, run)

    def triage_inbox(self, limit: int = 50) -> list[TriageResult]:
        """Triage every unread email in the mailbox."""
        if self.mailbox is None:
            raise ValueError("triage_inbox needs a mailbox provider")
        return [self.triage(email) for email in self.mailbox.fetch_unread(limit)]

    def send_if_allowed(self, result: TriageResult) -> bool:
        """Send the draft only when policy cleared it. Returns whether it sent.

        Sending is a separate call rather than something `triage` does on its
        own: an agent that classifies and sends in one step gives the caller no
        place to stand between the decision and the consequence.
        """
        if self.mailbox is None:
            raise ValueError("send_if_allowed needs a mailbox provider")
        if not result.auto_send_allowed:
            self.mailbox.add_label(result.email_id, "needs-human")
            return False

        self.mailbox.send_reply(result.email_id, result.classification.draft_reply)
        self.mailbox.add_label(result.email_id, "auto-answered")
        return True

    # -- internals -------------------------------------------------------

    def _decide(self, email: Email, classification: Classification, run: RunResult) -> TriageResult:
        reasons = self.policy.evaluate(classification, email.body)

        # A run that halted (step limit, budget, provider failure) is never
        # trusted for auto-send, whatever the classification says.
        if run.halted_reason:
            reasons.append(f"run halted: {run.halted_reason}")

        return TriageResult(
            email_id=email.id,
            classification=classification,
            requires_human=bool(reasons),
            escalation_reasons=reasons,
            cost_usd=run.cost_usd,
            duration_ms=run.duration_ms,
            halted_reason=run.halted_reason,
        )
