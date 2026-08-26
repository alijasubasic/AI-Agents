"""Drafting first-contact emails, and refusing to send most of them.

    python -m agents.outreach.demo

Runs on the fixture leads and scripted drafts, so it works on a fresh clone with
no API key and no network. Nothing is sent in any configuration: the campaign is
in dry-run mode and the sender is a mock that records instead of sending.

The interesting output is not the email that passes. It is the four that do not,
each stopped by a different rule, none of which is visible in the draft itself.
"""

from __future__ import annotations

from agents.outreach.agent import OutreachAgent
from agents.outreach.fixtures import CAMPAIGN, SUPPRESSED
from agents.outreach.models import OutreachResult
from agents.outreach.providers import MockSender
from agents.outreach.scripted import provider_for
from agents.outreach.suppression import MemorySuppressionList
from agents.prospecting.agent import ProspectingAgent
from agents.prospecting.fixtures import AREA
from agents.prospecting.models import Lead, Platform
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for as plan_provider
from core.config import Settings
from core.console import configure_stdout


def leads(settings: Settings) -> list[Lead]:
    """The fixture area's businesses, found the same way the demo above finds them."""
    return (
        ProspectingAgent(
            places=[
                MockPlaces(Platform.GOOGLE_MAPS),
                MockPlaces(Platform.OPENSTREETMAP),
                MockPlaces(Platform.DIRECTORY),
            ],
            pages=MockPages(),
            provider=plan_provider(AREA.what),
            settings=settings,
        )
        .find(AREA)
        .leads
    )


def run(settings: Settings | None = None) -> list[OutreachResult]:
    """Draft one email per lead and apply the policy to each."""
    settings = settings or Settings.from_env()
    suppression = MemorySuppressionList(list(SUPPRESSED))
    sender = MockSender()

    from collections import Counter

    already_written: Counter[str] = Counter()
    results: list[OutreachResult] = []

    for lead in leads(settings)[: CAMPAIGN.max_emails]:
        agent = OutreachAgent(
            provider=provider_for(lead.name),
            campaign=CAMPAIGN,
            sender=sender,
            suppression=suppression,
            settings=settings,
        )
        result = agent.draft(lead, already_written=already_written)
        results.append(result)
        if result.recipient:
            already_written[result.recipient.split("@")[-1]] += 1

    return results


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("outreach demo - one email per business, and the reasons not to send it")
    print(f"mode={settings.mode}  model={settings.model}  campaign={CAMPAIGN.id}")

    results = run(settings)
    clear = [result for result in results if result.auto_send_allowed]

    print(f"\n{'=' * 78}\n1. What the policy decided\n{'=' * 78}")
    for result in results:
        mark = "  ok  " if result.auto_send_allowed else " STOP "
        print(f"\n[{mark}] {result.company}  ->  {result.recipient or 'keine Adresse'}")
        for blocker in result.blockers:
            print(f"          - {blocker}")

    print(f"\n{'=' * 78}\n2. The one email that cleared every rule\n{'=' * 78}")
    if clear:
        first = clear[0]
        print(f"\nAn: {first.recipient}\nBetreff: {first.email.subject}\n")
        print(first.message)
    else:
        print("\nNone of them did.")

    print(f"\n{'=' * 78}")
    print(
        f"{len(clear)} of {len(results)} drafts cleared the policy. "
        f"Nothing was sent: dry_run={CAMPAIGN.dry_run}."
    )
    print(
        "\nThe footer under the rule — who is writing, why this business, how to\n"
        "make it stop — is assembled in code, not by the model. A model that can\n"
        "rewrite the opt-out line is a model that will eventually drop it."
    )


if __name__ == "__main__":
    main()
