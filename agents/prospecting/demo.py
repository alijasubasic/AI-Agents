"""Finding businesses in an area, with every source shown.

    python -m agents.prospecting.demo

Runs on the fixture platforms, so it works on a fresh clone with no API key and
no network. Four scenes, each showing one thing the pipeline has to get right:
the merge, the contact extraction, the guess it refuses to promote to a fact,
and the export a salesperson actually receives.
"""

from __future__ import annotations

from agents.prospecting.agent import ProspectingAgent, render_table
from agents.prospecting.fixtures import AREA
from agents.prospecting.models import ContactStatus, Platform, ProspectingResult
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for
from core.config import Settings
from core.console import configure_stdout


def run(settings: Settings | None = None) -> ProspectingResult:
    """Search the fixture area across three platforms."""
    settings = settings or Settings.from_env()

    agent = ProspectingAgent(
        places=[
            MockPlaces(Platform.GOOGLE_MAPS),
            MockPlaces(Platform.OPENSTREETMAP),
            MockPlaces(Platform.DIRECTORY),
        ],
        pages=MockPages(),
        provider=provider_for(AREA.what),
        settings=settings,
    )
    return agent.find(AREA)


def _scene_plan(result: ProspectingResult) -> None:
    print(f"\n{'=' * 78}\n1. The plan: the only thing the model contributes\n{'=' * 78}")
    plan = result.plan
    assert plan is not None
    print(f"  queries:  {' | '.join(plan.queries)}")
    print(f"  excluded: {', '.join(plan.exclude_terms)}")
    print(f"  because:  {plan.rationale}")
    print(
        f"\n  {result.listings_seen} listing(s) came back, "
        f"{result.duplicates_merged} were the same business twice."
    )


def _scene_merge(result: ProspectingResult) -> None:
    print(f"\n{'=' * 78}\n2. The merge: three spellings, one business\n{'=' * 78}")
    for lead in result.leads:
        if len(lead.listings) < 2:
            continue
        print(f"\n  {lead.name}  —  confidence {lead.confidence:.2f}")
        for listing in lead.listings:
            print(f"    {listing.platform.label:<16} {listing.name}")
        for note in lead.notes:
            print(f"    note: {note}")


def _scene_contacts(result: ProspectingResult) -> None:
    print(f"\n{'=' * 78}\n3. The contact details, and what each one is worth\n{'=' * 78}")
    for lead in result.leads:
        print(f"\n  {lead.name}")
        for contact in lead.contacts:
            person = f"  [{contact.person}]" if contact.person else ""
            note = f"  — {contact.note}" if contact.note else ""
            print(
                f"    {contact.kind:<6} {contact.value:<44} "
                f"{contact.status.value:<12} {contact.found_on}{person}{note}"
            )
        if not lead.contacts:
            print("    nothing published anywhere")


def _scene_export(result: ProspectingResult) -> None:
    print(f"\n{'=' * 78}\n4. What a salesperson receives\n{'=' * 78}\n")
    print(render_table(result))

    guessed = [
        (lead.name, contact.value)
        for lead in result.leads
        for contact in lead.contacts
        if contact.status is ContactStatus.CONSTRUCTED
    ]
    print(
        f"\n  {len(result.contactable)} of {len(result.leads)} businesses have an address "
        f"they published themselves."
    )
    for name, address in guessed:
        print(f"  {name}: {address} is a pattern guess — shown, never sent to.")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("prospecting demo - businesses in one area, across three platforms")
    print(f"mode={settings.mode}  model={settings.model}  area={AREA.describe()}")

    result = run(settings)

    _scene_plan(result)
    _scene_merge(result)
    _scene_contacts(result)
    _scene_export(result)

    print(
        "\nNo model produced any of those addresses or numbers. Each one was "
        "copied\nfrom a listing or a page, and carries the URL it came from."
    )


if __name__ == "__main__":
    main()
