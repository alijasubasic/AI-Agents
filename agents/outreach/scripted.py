"""Scripted drafts for the outreach demo and tests.

Three of the five are the email a careful model writes. Two are not, and both
failures are ones that look completely fine in isolation:

* the Alpenblick draft claims "über 200 sanierte Dächer im Raum München" — a
  detail nobody retrieved, which the policy catches as an unbacked claim and
  the codex catches again as an unverified claim repeated to a stranger
* the Sailer draft is perfectly written and addressed to a guess

Neither the model nor the draft is at fault in a way anyone could see by
reading it. That is why the checks are not left to a reader.
"""

from __future__ import annotations

from agents.outreach.models import OutreachEmail
from core.llm import MockProvider, text_response

DRAFTS: dict[str, OutreachEmail] = {
    "Reiter Bedachungen GmbH": OutreachEmail(
        subject="Anschlagpunkte für Steildächer — kurze Frage",
        greeting="Guten Tag Martin Reiter,",
        body=(
            "wir liefern Sicherungssysteme und Anschlagpunkte für Steildächer, "
            "jeweils mit Montageplan und Prüfprotokoll. Weil Ihr Betrieb in "
            "München überwiegend Steildächer macht, passt das Sortiment "
            "vermutlich direkt auf Ihre Baustellen.\n\n"
            "Hätten Sie kommende Woche zehn Minuten für ein Telefonat? Dann "
            "kann ich Ihnen sagen, ob sich das für Ihre Projekte rechnet — und "
            "wenn nicht, sage ich Ihnen das genauso."
        ),
        personalisation="Steildach-Betrieb in München, Ansprechpartner im Impressum benannt.",
        facts_used=["Reiter Bedachungen GmbH", "München", "Dachdecker", "Martin Reiter"],
    ),
    "Dachdeckerei Sailer & Sohn": OutreachEmail(
        subject="Sicherungssysteme für Steildächer",
        greeting="Guten Tag Stefan Sailer,",
        body=(
            "wir liefern Anschlagpunkte und Sicherungssysteme für Steildächer, "
            "inklusive Montageplan und Prüfprotokoll. Für einen Betrieb Ihrer "
            "Größe in München ist vor allem die Lieferzeit interessant, deshalb "
            "melde ich mich direkt.\n\n"
            "Wenn es passt, rufe ich kurz an — sagen Sie einfach, wann es Ihnen "
            "recht ist."
        ),
        personalisation="Dachdeckerei in München mit benanntem Inhaber.",
        facts_used=["Dachdeckerei Sailer & Sohn", "München", "Dachdecker", "Stefan Sailer"],
    ),
    "Alpenblick Dach & Fassade": OutreachEmail(
        subject="Anschlagpunkte für Ihre Dachsanierungen",
        greeting="Guten Tag,",
        body=(
            "bei über 200 sanierten Dächern im Raum München kennen Sie das "
            "Thema Absturzsicherung besser als die meisten. Wir liefern "
            "Anschlagpunkte und Sicherungssysteme für Steildächer, mit "
            "Montageplan und Prüfprotokoll.\n\n"
            "Passt ein kurzes Telefonat in den nächsten Tagen?"
        ),
        personalisation="Dach- und Fassadenbetrieb in München.",
        facts_used=[
            "Alpenblick Dach & Fassade",
            "München",
            "über 200 sanierten Dächern im Raum München",
        ],
    ),
    "Bauzentrum Isartal e.K.": OutreachEmail(
        subject="Anschlagpunkte und Sicherungssysteme — Anfrage",
        greeting="Guten Tag,",
        body=(
            "wir liefern Sicherungssysteme und Anschlagpunkte für Steildächer, "
            "jeweils mit Montageplan und Prüfprotokoll. Da Sie in München "
            "Dachdecker- und Spenglerarbeiten anbieten, könnte das zu Ihren "
            "Aufträgen passen.\n\n"
            "Wenn Sie mögen, schicke ich Ihnen die Unterlagen — oder wir "
            "telefonieren kurz."
        ),
        personalisation="Dachdeckerei und Spenglerei in München.",
        facts_used=["Bauzentrum Isartal e.K.", "München", "Spenglerei"],
    ),
    "Nordwind Dachtechnik GmbH": OutreachEmail(
        subject="Sicherungssysteme für Flachdach und Steildach",
        greeting="Guten Tag Ines Brandl,",
        body=(
            "wir liefern Anschlagpunkte und Sicherungssysteme für Steil- und "
            "Flachdächer, mit Montageplan und Prüfprotokoll. Ihr Betrieb in "
            "München arbeitet in beiden Bereichen, deshalb schreibe ich Ihnen.\n\n"
            "Hätten Sie kurz Zeit für ein Telefonat?"
        ),
        personalisation="Dachdeckerbetrieb mit Flachdach-Schwerpunkt in München.",
        facts_used=["Nordwind Dachtechnik GmbH", "München", "Flachdach", "Ines Brandl"],
    ),
}


def provider_for(company: str, *, model: str = "claude-opus-5") -> MockProvider:
    """Build a scripted provider for one company's draft.

    One provider per lead, matching how `agents/supervisor/pipeline.py` builds one
    per email: a single provider replaying five drafts in order would break the
    moment a lead with no address skipped its model call.
    """
    if company not in DRAFTS:
        raise KeyError(f"No scripted draft for {company!r}")
    return MockProvider([text_response(DRAFTS[company].model_dump_json())], model=model)
