"""Eval cases for the outreach agent.

Every case here is about something *not* happening. That is what an outbound
system needs measured: the emails it did not send, to the addresses nobody
published, to the people who asked to be left alone.
"""

from __future__ import annotations

from collections import Counter

from agents.outreach.agent import OutreachAgent, candidate_address
from agents.outreach.fixtures import CAMPAIGN, SUPPRESSED
from agents.outreach.models import OutreachEmail, OutreachResult, render_message
from agents.outreach.policy import DEFAULT_POLICY, unbacked_claims
from agents.outreach.providers import MockSender
from agents.outreach.scripted import provider_for
from agents.outreach.suppression import MemorySuppressionList
from agents.prospecting.agent import ProspectingAgent
from agents.prospecting.fixtures import AREA
from agents.prospecting.models import ContactStatus, Lead, Platform
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for as plan_provider
from core.config import Settings
from evals.models import Expectation, Layer, Score
from evals.registry import case
from evals.scoring import combine, contains_all, equals, is_false, is_true

AGENT = "outreach"


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def _leads() -> list[Lead]:
    return (
        ProspectingAgent(
            places=[
                MockPlaces(Platform.GOOGLE_MAPS),
                MockPlaces(Platform.OPENSTREETMAP),
                MockPlaces(Platform.DIRECTORY),
            ],
            pages=MockPages(),
            provider=plan_provider(AREA.what),
            settings=_settings(),
        )
        .find(AREA)
        .leads
    )


def _lead(name: str) -> Lead:
    return next(lead for lead in _leads() if lead.name == name)


def _draft(name: str, *, dry_run: bool = True, sender: MockSender | None = None) -> OutreachResult:
    lead = _lead(name)
    agent = OutreachAgent(
        provider=provider_for(lead.name),
        campaign=CAMPAIGN.model_copy(update={"dry_run": dry_run}),
        sender=sender,
        suppression=MemorySuppressionList(list(SUPPRESSED)),
        settings=_settings(),
    )
    result = agent.draft(lead)
    if sender is not None:
        agent.send(result, approved=True)
    return result


# --- What goes out ------------------------------------------------------


@case(
    id="outreach-clean-lead-clears-the-policy",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A confirmed address and an honest draft produce a sendable email.",
)
def _() -> Score:
    result = _draft("Reiter Bedachungen GmbH")
    return combine(
        is_true(result.auto_send_allowed, label="sendable"),
        equals(result.blockers, [], label="blockers"),
        equals(result.recipient_status, ContactStatus.CONFIRMED, label="recipient status"),
    )


@case(
    id="outreach-footer-is-always-complete",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Every message identifies the sender, the reason, and the way out.",
)
def _() -> Score:
    result = _draft("Reiter Bedachungen GmbH")
    return contains_all(
        result.message,
        ["Sturmfest Systeme GmbH", "Impressum:", "Abmelden", "gefunden über"],
        label="footer",
    )


@case(
    id="outreach-no-guessed-salutation",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A named person is greeted by name, never by a guessed form of address.",
)
def _() -> Score:
    result = _draft("Reiter Bedachungen GmbH")
    return combine(
        is_true("Guten Tag Martin Reiter," in result.message, label="named greeting"),
        is_false("Herr" in result.message, label="guessed salutation"),
    )


# --- What does not go out -----------------------------------------------


@case(
    id="outreach-guessed-address-is-refused",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A pattern-built address never receives an email.",
)
def _() -> Score:
    result = _draft("Dachdeckerei Sailer & Sohn")
    return combine(
        is_false(result.auto_send_allowed, label="sendable"),
        equals(result.recipient_status, ContactStatus.CONSTRUCTED, label="recipient status"),
    )


@case(
    id="outreach-directory-address-is-refused",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An address only a directory knows is held for a person.",
)
def _() -> Score:
    result = _draft("Alpenblick Dach & Fassade")
    return is_false(result.auto_send_allowed, label="sendable")


@case(
    id="outreach-opt-out-beats-a-perfect-lead",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The best lead in the run is the one nobody may write to.",
)
def _() -> Score:
    result = _draft("Nordwind Dachtechnik GmbH")
    return combine(
        is_true(result.suppressed, label="suppressed"),
        is_false(result.auto_send_allowed, label="sendable"),
    )


@case(
    id="outreach-invented-claim-is-caught",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A project count nobody retrieved is reported as unbacked.",
)
def _() -> Score:
    result = _draft("Alpenblick Dach & Fassade")
    return equals(
        result.unbacked_claims,
        ["über 200 sanierten Dächern im Raum München"],
        label="unbacked claims",
    )


@case(
    id="outreach-town-name-does-not-back-a-claim",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A real town inside an invented sentence does not make it true.",
)
def _() -> Score:
    lead = _lead("Reiter Bedachungen GmbH")
    email = OutreachEmail(
        subject="s",
        greeting="Guten Tag,",
        body="b",
        facts_used=["über 200 sanierte Dächer im Raum München"],
    )
    return equals(len(unbacked_claims(email, lead, CAMPAIGN)), 1, label="unbacked claims")


@case(
    id="outreach-one-email-per-firm",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A second draft to a domain already written to is refused.",
)
def _() -> Score:
    lead = _lead("Reiter Bedachungen GmbH")
    contact = candidate_address(lead)
    email = OutreachEmail(subject="s", greeting="Guten Tag,", body="b")

    reasons = DEFAULT_POLICY.evaluate(
        lead,
        contact,
        email,
        render_message(email, CAMPAIGN),
        campaign=CAMPAIGN,
        already_written=Counter({"reiter-bedachungen.example": 1}),
    )
    return is_true(any("bereits" in reason for reason in reasons), label="rate limited")


# --- Sending ------------------------------------------------------------


@case(
    id="outreach-dry-run-sends-nothing",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An approved, policy-clean draft still does not go out in dry run.",
)
def _() -> Score:
    sender = MockSender()
    result = _draft("Reiter Bedachungen GmbH", dry_run=True, sender=sender)
    return combine(
        is_true(result.auto_send_allowed, label="would be sendable"),
        equals(sender.sent, [], label="messages sent"),
    )


@case(
    id="outreach-three-yesses-send-one-email",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Policy, approval and dry-run off together send exactly one message.",
)
def _() -> Score:
    sender = MockSender()
    _draft("Reiter Bedachungen GmbH", dry_run=False, sender=sender)
    return equals(sender.recipients, ["m.reiter@reiter-bedachungen.example"], label="recipients")


@case(
    id="outreach-suppressed-lead-never-sends",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Approval and dry-run off do not override an opt-out.",
)
def _() -> Score:
    sender = MockSender()
    _draft("Nordwind Dachtechnik GmbH", dry_run=False, sender=sender)
    return equals(sender.sent, [], label="messages sent")


# --- Known gaps ---------------------------------------------------------


@case(
    id="outreach-body-claims-are-not-checked",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An invented claim in the body is caught even when facts_used omits it.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "The claims check reads facts_used, which the model fills in itself. A "
        "model that writes 'Testsieger 2025' in the body and leaves the list "
        "empty passes here, and only the codex's A2 might catch it — and only if "
        "something else already flagged the claim. Checking the prose itself "
        "needs entailment, not a token scan."
    ),
)
def _() -> Score:
    lead = _lead("Reiter Bedachungen GmbH")
    email = OutreachEmail(
        subject="Anschlagpunkte",
        greeting="Guten Tag,",
        body="als Testsieger 2025 wissen Sie, worauf es ankommt.",
        facts_used=[],
    )
    reasons = DEFAULT_POLICY.evaluate(
        lead,
        candidate_address(lead),
        email,
        render_message(email, CAMPAIGN),
        campaign=CAMPAIGN,
    )
    return is_true(any("unbelegt" in reason for reason in reasons), label="claim caught")


@case(
    id="outreach-address-is-never-tested-for-delivery",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An address at a domain that accepts no mail is refused before sending.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Syntax is checked, existence is not: no MX lookup, no verification "
        "service. A typo in a published imprint is therefore sent to and bounces, "
        "and enough bounces damage the sending domain's reputation. The fix costs "
        "a DNS lookup per address and has not been added."
    ),
)
def _() -> Score:
    from agents.prospecting.models import ContactPoint

    lead = _lead("Reiter Bedachungen GmbH")
    typo = ContactPoint(
        kind="email",
        value="inffo@reiter-bedachungen.example",
        status=ContactStatus.CONFIRMED,
        platform=Platform.WEBSITE,
        source_url="https://reiter-bedachungen.example/impressum",
    )
    email = OutreachEmail(subject="s", greeting="Guten Tag,", body="b")
    reasons = DEFAULT_POLICY.evaluate(
        lead, typo, email, render_message(email, CAMPAIGN), campaign=CAMPAIGN
    )
    return is_true(bool(reasons), label="undeliverable address refused")


@case(
    id="outreach-cannot-read-a-reply",
    agent=AGENT,
    layer=Layer.LOGIC,
    description='A recipient answering "Abmelden" is added to the suppression list.',
    expectation=Expectation.KNOWN_GAP,
    note=(
        "The message promises that answering with 'Abmelden' stops further "
        "contact, and nothing in this package reads replies — a person has to "
        "add the entry by hand. The promise is kept by whoever runs the campaign, "
        "not by the code, and that is the wrong place for it. Wiring "
        "`email-triage` to `FileSuppressionList.add` is the obvious next step."
    ),
)
def _() -> Score:
    return is_true(
        hasattr(OutreachAgent, "process_reply"),
        label="replies are processed automatically",
    )
