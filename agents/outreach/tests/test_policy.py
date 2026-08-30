"""Tests for the outreach policy.

This is the part that decides whether a stranger receives an email, so it gets
the densest coverage in the package. Every rule gets a case that fires it and a
case that does not — a guard nobody has watched not fire is a guard that might
be blocking everything.
"""

from __future__ import annotations

from collections import Counter

from agents.outreach.models import Campaign, OutreachEmail, Sender, render_message
from agents.outreach.policy import DEFAULT_POLICY, OutreachPolicy, unbacked_claims
from agents.outreach.suppression import MemorySuppressionList
from agents.prospecting.models import ContactPoint, ContactStatus, Lead, Platform

SENDER = Sender(
    name="Lena Hartwig",
    company="Sturmfest Systeme GmbH",
    email="l.hartwig@sturmfest-systeme.example",
    website="https://sturmfest-systeme.example",
    imprint_url="https://sturmfest-systeme.example/impressum",
)

CAMPAIGN = Campaign(
    id="camp-test",
    sender=SENDER,
    goal="Ein kurzes Telefonat.",
    offer="Sicherungssysteme für Steildächer.",
)


def lead(**overrides) -> Lead:
    base = {
        "id": "lead-01",
        "name": "Reiter Bedachungen GmbH",
        "city": "München",
        "website": "https://reiter-bedachungen.example",
        "categories": ["Dachdecker"],
        "confidence": 0.9,
    }
    return Lead(**{**base, **overrides})


def contact(status: ContactStatus = ContactStatus.CONFIRMED, **overrides) -> ContactPoint:
    base = {
        "kind": "email",
        "value": "info@reiter-bedachungen.example",
        "status": status,
        "platform": Platform.WEBSITE,
        "source_url": "https://reiter-bedachungen.example/impressum",
    }
    return ContactPoint(**{**base, **overrides})


#: The baseline recipient: an address the business published itself.
DEFAULT_CONTACT = contact()


def email(**overrides) -> OutreachEmail:
    base = {
        "subject": "Anschlagpunkte für Steildächer",
        "greeting": "Guten Tag,",
        "body": (
            "wir liefern Sicherungssysteme für Steildächer, mit Montageplan und "
            "Prüfprotokoll. Hätten Sie kurz Zeit für ein Telefonat?"
        ),
        "facts_used": ["Reiter Bedachungen GmbH", "München", "Dachdecker"],
    }
    return OutreachEmail(**{**base, **overrides})


def evaluate(
    *,
    policy: OutreachPolicy = DEFAULT_POLICY,
    lead_override: Lead | None = None,
    point: ContactPoint | None = DEFAULT_CONTACT,
    draft: OutreachEmail | None = None,
    message: str | None = None,
    suppression: MemorySuppressionList | None = None,
    already_written: Counter[str] | None = None,
) -> list[str]:
    subject = lead_override or lead()
    draft = draft or email()
    return policy.evaluate(
        subject,
        point,
        draft,
        message if message is not None else render_message(draft, CAMPAIGN),
        campaign=CAMPAIGN,
        suppression=suppression,
        already_written=already_written,
    )


# --- The baseline -------------------------------------------------------


def test_a_clean_draft_to_a_confirmed_address_clears_everything():
    assert evaluate() == []


# --- Consent and provenance ---------------------------------------------


def test_a_guessed_address_is_never_written_to():
    reasons = evaluate(point=contact(ContactStatus.CONSTRUCTED))

    assert any("constructed" in reason for reason in reasons)


def test_a_directory_address_is_not_enough_on_its_own():
    reasons = evaluate(point=contact(ContactStatus.REPORTED))

    assert any("reported" in reason for reason in reasons)


def test_a_no_reply_address_is_refused():
    reasons = evaluate(point=contact(ContactStatus.INVALID, value="noreply@reiter.example"))

    assert any("nimmt keine Post an" in reason for reason in reasons)


def test_a_lead_with_no_address_is_refused_rather_than_improvised():
    assert evaluate(point=None) == ["keine E-Mail-Adresse vorhanden"]


def test_someone_who_asked_to_be_left_alone_is_left_alone():
    reasons = evaluate(
        suppression=MemorySuppressionList(["info@reiter-bedachungen.example"]),
    )

    assert any("Sperrliste" in reason for reason in reasons)


def test_one_mailbox_opting_out_covers_the_whole_firm():
    reasons = evaluate(suppression=MemorySuppressionList(["@reiter-bedachungen.example"]))

    assert any("Sperrliste" in reason for reason in reasons)


def test_a_weakly_supported_business_is_not_written_to():
    reasons = evaluate(lead_override=lead(confidence=0.3))

    assert any("Konfidenz" in reason for reason in reasons)


# --- Volume -------------------------------------------------------------


def test_a_firm_is_written_to_once_per_campaign():
    reasons = evaluate(already_written=Counter({"reiter-bedachungen.example": 1}))

    assert any("bereits" in reason for reason in reasons)


def test_a_domain_nobody_has_written_to_passes():
    assert evaluate(already_written=Counter({"someone-else.example": 3})) == []


# --- What the message says ----------------------------------------------


def test_a_message_with_no_opt_out_is_refused():
    reasons = evaluate(message="Guten Tag, wir liefern Sicherungssysteme. Sturmfest Systeme GmbH")

    assert "kein Abmeldehinweis im Text" in reasons


def test_a_message_that_does_not_say_who_sent_it_is_refused():
    reasons = evaluate(message="Guten Tag, Sie können sich jederzeit abmelden.")

    assert "Absender ist im Text nicht identifizierbar" in reasons


def test_pressure_selling_is_refused():
    reasons = evaluate(draft=email(body="Nur heute: melden Sie sich, letzte Chance."))

    assert any("Verknappung" in reason or "Drucksprache" in reason for reason in reasons)


def test_a_price_nobody_authorised_is_refused():
    reasons = evaluate(draft=email(body="Das Set kostet 890 € pro Dach."))

    assert any("Preis" in reason for reason in reasons)


def test_an_empty_draft_is_refused():
    reasons = evaluate(draft=email(subject="", body=""))

    assert "kein Betreff" in reasons
    assert "kein Text" in reasons


def test_an_essay_is_refused():
    reasons = evaluate(draft=email(body="Dach " * 200))

    assert any("Wörter lang" in reason for reason in reasons)


def test_reasons_accumulate_rather_than_stopping_at_the_first():
    reasons = evaluate(
        point=contact(ContactStatus.CONSTRUCTED),
        lead_override=lead(confidence=0.2),
        draft=email(body="Nur heute: 20 % Rabatt, garantiert."),
    )

    assert len(reasons) >= 4


# --- Claims -------------------------------------------------------------


def test_a_fact_from_the_record_is_backed():
    assert unbacked_claims(email(), lead(), CAMPAIGN) == []


def test_an_invented_project_count_is_not_backed():
    """The case a substring check got wrong: the town name is real, the rest is not."""
    claims = unbacked_claims(
        email(facts_used=["über 200 sanierte Dächer im Raum München"]), lead(), CAMPAIGN
    )

    assert claims == ["über 200 sanierte Dächer im Raum München"]


def test_an_unbacked_claim_blocks_the_send():
    reasons = evaluate(draft=email(facts_used=["Testsieger 2025"]))

    assert any("unbelegte Angabe" in reason for reason in reasons)


def test_a_looser_policy_can_be_configured_but_is_not_the_default():
    permissive = OutreachPolicy(require_confirmed_email=False)

    assert evaluate(policy=permissive, point=contact(ContactStatus.REPORTED)) == []
    assert DEFAULT_POLICY.require_confirmed_email
