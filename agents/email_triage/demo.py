"""Runnable demonstration of the email triage agent.

    python -m agents.email_triage.demo

Runs on the mock provider against the synthetic fixture inbox — no API key, no
mailbox, no network. Six emails, chosen so that every escalation path fires at
least once.
"""

from __future__ import annotations

from agents.email_triage.agent import EmailTriageAgent
from agents.email_triage.fixtures import INBOX
from agents.email_triage.models import TriageResult
from agents.email_triage.providers import MockCrm, MockMailbox
from agents.email_triage.scripted import provider_for
from core.config import Settings
from core.console import configure_stdout


def route_label(result: TriageResult, sent: bool) -> str:
    """Name the route this email took.

    Three outcomes, not two: spam is filed without a reply and without a human
    ever seeing it, which is neither of the other two.
    """
    if sent:
        return "AUTO-REPLY"
    if result.requires_human:
        return "-> HUMAN"
    return "ARCHIVED"


def triage_all(settings: Settings | None = None) -> list[tuple[TriageResult, bool]]:
    """Triage the whole fixture inbox, returning each result and whether it sent.

    A fresh agent per email keeps each scripted provider matched to its own
    message; in live mode one agent would handle the whole inbox.
    """
    settings = settings or Settings.from_env()
    mailbox = MockMailbox()
    outcomes: list[tuple[TriageResult, bool]] = []

    for email in INBOX:
        agent = EmailTriageAgent(
            provider=provider_for(email.id),
            crm=MockCrm(),
            mailbox=mailbox,
            settings=settings,
        )
        result = agent.triage(email)
        outcomes.append((result, agent.send_if_allowed(result)))

    return outcomes


def _print(email_subject: str, result: TriageResult, sent: bool) -> None:
    c = result.classification
    print(f"\n{'-' * 74}")
    print(f"{result.email_id}  {email_subject[:56]}")
    print(f"{'-' * 74}")
    print(
        f"  {c.priority.value:<7} | {c.intent.value:<12} | {c.sentiment.value:<8} "
        f"| confidence {c.confidence:.2f}"
    )
    print(f"  {c.summary}")

    if c.tasks:
        print("  tasks:")
        for task in c.tasks:
            due = f"  (due {task.due_date})" if task.due_date else ""
            print(f"    - {task.description}{due}")

    print(f"\n  route: {route_label(result, sent)}")
    for reason in result.escalation_reasons:
        print(f"    ! {reason}")
    if not sent and not result.escalation_reasons:
        print("    ! spam — filed without a reply, no human needed")

    print(f"  cost: ${result.cost_usd:.6f}  |  {result.duration_ms:.0f} ms")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("email-triage demo")
    print(f"mode={settings.mode}  model={settings.model}  inbox={len(INBOX)} messages")

    outcomes = triage_all(settings)
    subjects = {email.id: email.subject for email in INBOX}
    for result, sent in outcomes:
        _print(subjects[result.email_id], result, sent)

    auto = sum(1 for _, sent in outcomes if sent)
    escalated = sum(1 for r, _ in outcomes if r.requires_human)
    total_cost = sum(r.cost_usd for r, _ in outcomes)

    print(f"\n{'=' * 74}")
    print(
        f"{len(outcomes)} triaged | {auto} auto-replied | {escalated} escalated "
        f"| ${total_cost:.6f} total"
    )
    print("Escalation is decided by deterministic policy, not by the model — see policy.py.")


if __name__ == "__main__":
    main()
