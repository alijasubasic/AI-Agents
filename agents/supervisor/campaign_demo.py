"""The whole outbound chain, supervised.

    python -m agents.supervisor.campaign_demo

The supervisor drives `prospecting` over three fixture platforms, has `outreach`
draft one email per business it found, reviews every decision against the codex
and the reviewing model, and sends exactly the ones that survived — which, in
dry-run mode, is none of them.

No API key, no network, nothing sent. The lead list goes to `leads/`, which is
git-ignored, because a file of other people's contact details does not belong in
a repository.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from agents.outreach.fixtures import CAMPAIGN, SUPPRESSED
from agents.outreach.providers import MockSender
from agents.outreach.scripted import provider_for as draft_provider
from agents.outreach.suppression import MemorySuppressionList
from agents.prospecting.fixtures import AREA
from agents.prospecting.models import Lead, Platform
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for as plan_provider
from agents.supervisor.campaign import (
    CampaignResult,
    LeadCampaign,
    lead_sheet,
    outreach_sheet,
    render_summary,
)
from agents.supervisor.models import Verdict
from agents.supervisor.scripted import judge_provider
from agents.supervisor.spreadsheet import build_writer
from core.config import Settings
from core.console import configure_stdout

#: Fixed so the export path and the demo output are reproducible.
RUN_DATE = date(2026, 3, 6)

OUTPUT_DIR = Path("leads")

_MARK = {
    Verdict.APPROVED: "  ok   ",
    Verdict.HOLD_FOR_HUMAN: " HOLD  ",
    Verdict.BLOCKED: " BLOCK ",
}


def run(settings: Settings | None = None) -> CampaignResult:
    """Run one campaign over the fixture area."""
    settings = settings or Settings.from_env()

    return LeadCampaign(
        area=AREA,
        campaign=CAMPAIGN,
        places=[
            MockPlaces(Platform.GOOGLE_MAPS),
            MockPlaces(Platform.OPENSTREETMAP),
            MockPlaces(Platform.DIRECTORY),
        ],
        pages=MockPages(),
        planner=plan_provider(AREA.what),
        draft_provider=lambda lead: draft_provider(lead.name),
        judge=judge_provider,
        sender=MockSender(),
        suppression=MemorySuppressionList(list(SUPPRESSED)),
        settings=settings,
    ).run()


def _contact_line(lead: Lead) -> str:
    person = lead.primary_person()
    email = lead.best_email() or next(iter(lead.emails), None)
    phone = lead.best_phone()
    return (
        f"  {lead.name[:32]:<33} "
        f"{(person.name if person else '—')[:18]:<19} "
        f"{(email.value if email else '—')[:37]:<38} "
        f"{(phone.value if phone else '—'):<16}"
    )


def _print(result: CampaignResult) -> None:
    print(f"\n{'=' * 78}\nWhat the campaign found\n{'=' * 78}")
    print(render_summary(result))

    print(f"\n{'=' * 78}\nName, E-Mail, Telefon\n{'=' * 78}")
    print(f"  {'Firma':<33} {'Ansprechpartner':<19} {'E-Mail':<38} {'Telefon':<16}")
    print("  " + "-" * 106)
    for lead in result.leads:
        print(_contact_line(lead))

    print(f"\n{'=' * 78}\nWhat the supervisor decided about writing to them\n{'=' * 78}")
    for review in result.reviews:
        decision = review.decision
        print(f"[{_MARK[review.verdict]}] {decision.agent:<12} {decision.subject[:48]}")
        for reason in review.reasons:
            print(f"            - {reason}")

    print(f"\n{'=' * 78}")
    print(
        f"{len(result.approved)} approved | {len(result.held)} held | "
        f"{len(result.blocked)} blocked | sent {len(result.sent_to)} | "
        f"${result.total_cost_usd:.4f}"
    )


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("campaign demo - the supervisor steering prospecting and outreach")
    print(f"mode={settings.mode}  model={settings.model}  area={AREA.describe()}")

    result = run(settings)
    _print(result)

    destination = OUTPUT_DIR / f"{RUN_DATE:%Y-%m-%d}-{result.campaign.id}"
    written = build_writer("csv").write([lead_sheet(result), outreach_sheet(result)], destination)

    print(f"\n{'=' * 78}")
    print("Lead list written:")
    for path in written:
        print(f"  {path}")

    print(
        "\nEvery address in that file carries the page it was published on. The\n"
        "ones that do not are labelled `geraten`, and nothing in this system will\n"
        "send to them — not the policy, not the codex, and not by accident."
    )


if __name__ == "__main__":
    main()
