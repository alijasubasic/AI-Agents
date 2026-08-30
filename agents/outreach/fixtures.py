"""The campaign the demo runs, and the list of people it must not write to.

Invented, like everything else here. The sender is a fictional supplier of roof
safety systems writing to the fictional roofers in
`agents/prospecting/fixtures.py`, and every address is on a `.example` domain
that cannot resolve.

`SUPPRESSED` carries one domain-level entry, which is the case worth having in
a fixture set: Nordwind Dachtechnik is the *best* lead in the run — three
platforms, a named managing director, a confirmed personal address — and it is
the one nobody may write to. A suppression list that only ever blocks weak leads
has never actually been tested.
"""

from __future__ import annotations

from agents.outreach.models import Campaign, Language, Sender
from agents.outreach.suppression import SuppressionEntry

SENDER = Sender(
    name="Lena Hartwig",
    role="Vertrieb Handwerk",
    company="Sturmfest Systeme GmbH",
    email="l.hartwig@sturmfest-systeme.example",
    website="https://sturmfest-systeme.example",
    address="Gewerbepark 4, 85560 Ebersberg",
    imprint_url="https://sturmfest-systeme.example/impressum",
    # Stored, and deliberately not printed in the message body — see the note
    # on `Sender.phone`.
    phone="+49 8092 5550100",
)

CAMPAIGN = Campaign(
    id="camp-2026-03-dach-muenchen",
    sender=SENDER,
    goal="Ein kurzes Telefonat darüber, ob unsere Sicherungssysteme zu ihren Dachprojekten passen.",
    offer=(
        "Sicherungssysteme und Anschlagpunkte für Steildächer, geliefert mit "
        "Montageplan und Prüfprotokoll."
    ),
    language=Language.DE,
    dry_run=True,
    max_emails=10,
)

SUPPRESSED: list[SuppressionEntry] = [
    SuppressionEntry(
        value="@nordwind-dachtechnik.example",
        reason="hat 2025 um Löschung gebeten",
    ),
]
