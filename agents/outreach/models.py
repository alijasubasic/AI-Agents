"""Data models for outreach.

The same split as everywhere else in this repository: what the **model** wrote,
and what the **system** decided about it.

:class:`OutreachEmail` is the model's work — a subject line, a greeting, a short
body, and a list of which facts about the business it used. Everything legally
required is *not* the model's work: the sender identification, the reason this
business is being written to, and the opt-out sentence are assembled by
:func:`render_message` in plain code, because a footer that a model rewrites
because it thought of a nicer phrasing is a footer that eventually goes missing.

:class:`OutreachResult` adds the decision made by `policy.py`, which the model
is never asked for.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agents.prospecting.models import ContactStatus, Lead


class Language(StrEnum):
    DE = "de"
    EN = "en"


class Sender(BaseModel):
    """Who is writing, in the detail a recipient needs to identify them.

    `phone` is stored and deliberately kept out of the message body: codex
    article A5 flags any phone number in outbound text, and a signature that
    trips a guardrail on every single send teaches everyone to ignore it.
    Prospects who want to call use the number in the imprint the footer links.
    """

    name: str
    role: str = ""
    company: str
    email: str
    website: str = ""
    address: str = ""
    imprint_url: str = ""
    phone: str = ""


class Campaign(BaseModel):
    """One outreach run: who is writing, to what end, under which limits."""

    id: str
    sender: Sender
    goal: str = Field(description="What a reply would lead to, in one sentence.")
    offer: str = Field(description="What is being offered, in the sender's own words.")
    language: Language = Language.DE

    #: Nothing is sent unless this is explicitly turned off. Every default in
    #: this package points at "draft it, show it to a person, stop".
    dry_run: bool = True
    max_emails: int = Field(default=25, ge=1, le=500)

    def known_facts(self, lead: Lead) -> list[str]:
        """Everything the model is allowed to treat as true about this business.

        Assembled from the lead record and the campaign, never from the model.
        `policy.evaluate` checks the model's `facts_used` against this list, so
        a flattering detail nobody retrieved cannot reach a stranger's inbox.
        """
        facts = [lead.name, lead.city, lead.website, self.offer, self.goal]
        facts += lead.categories
        person = lead.primary_person()
        if person:
            facts += [person.name, person.role]
        for listing in lead.listings:
            facts.append(listing.platform.label)
            if listing.rating is not None:
                facts.append(f"{listing.rating}")
        return [fact for fact in facts if fact]


class OutreachEmail(BaseModel):
    """What the model wrote. Field descriptions are the prompt."""

    subject: str = Field(
        description=(
            "A plain subject line naming the concrete reason for writing. No "
            "urgency, no question marks designed to provoke a click, under 60 "
            "characters."
        )
    )
    greeting: str = Field(
        description=(
            'The salutation. With a named person: "Guten Tag Martin Reiter," — '
            "first name and surname, because a form of address guessed from a "
            'name is wrong often enough to matter. With no name: "Guten Tag,".'
        )
    )
    body: str = Field(
        description=(
            "Three to five sentences. Say why this specific business, what is "
            "offered, and what a reply would lead to. No prices, no discounts, "
            "no deadlines, no claims about their business that were not given "
            "to you."
        )
    )
    personalisation: str = Field(
        default="",
        description="One sentence on what in the record made this business relevant.",
    )
    facts_used: list[str] = Field(
        default_factory=list,
        description=(
            "Every fact about the recipient's business that the text relies on, "
            "copied from the record you were given. A fact that is not in the "
            "record blocks the send, so list exactly what you used."
        ),
    )


class OutreachResult(BaseModel):
    """One drafted email plus the deterministic decision about sending it."""

    lead_id: str
    company: str
    recipient: str | None = None
    recipient_status: ContactStatus | None = None
    person: str | None = None

    email: OutreachEmail
    message: str = Field(default="", description="The assembled text, footer included.")
    source_url: str = ""

    requires_human: bool = True
    blockers: list[str] = Field(default_factory=list)
    unbacked_claims: list[str] = Field(default_factory=list)

    #: Whether this recipient has asked not to be contacted. Carried as its own
    #: field rather than left inside `blockers` as a sentence: the codex blocks
    #: on it outright, and a guarantee that depends on parsing a German string
    #: is not a guarantee.
    suppressed: bool = False

    sent: bool = False
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    halted_reason: str | None = None

    @property
    def auto_send_allowed(self) -> bool:
        """True only when nothing at all objected.

        Note what this does *not* consider: whether the campaign is in dry-run
        mode, and whether the supervisor approved. Both are checked at the point of
        sending. This property answers one question — did the policy find a
        reason not to — and answering exactly one question is what makes it
        testable.
        """
        return not self.requires_human and not self.blockers and self.halted_reason is None


def render_message(email: OutreachEmail, campaign: Campaign, result_source: str = "") -> str:
    """Assemble the text that actually goes out.

    The model wrote the greeting and the body. Everything below the rule is
    written here, in code:

    * who is writing, with a link to their imprint
    * why this business was contacted, naming the platform it was found on
    * how to never hear from us again, in one sentence, at the end

    German law wants the first two for commercial email and the third for any
    further contact; more to the point, a cold email that hides where the
    address came from is the kind that gets reported, and being reported is a
    deliverability problem long before it is a legal one.
    """
    sender = campaign.sender
    identification = [
        f"{sender.name}" + (f", {sender.role}" if sender.role else ""),
        sender.company,
    ]
    if sender.address:
        identification.append(sender.address)
    if sender.website:
        identification.append(sender.website)
    if sender.imprint_url:
        identification.append(f"Impressum: {sender.imprint_url}")

    provenance = (
        f"Wir schreiben Ihnen einmalig, weil {sender.company} Betriebe in Ihrer "
        f"Branche anspricht und Ihr Eintrag öffentlich zugänglich ist"
    )
    provenance += f" ({result_source})." if result_source else "."

    opt_out = (
        "Wenn Sie keine weitere Nachricht von uns möchten, antworten Sie bitte "
        "kurz mit „Abmelden“ — wir vermerken das dauerhaft und schreiben Ihnen "
        "nicht wieder."
    )

    return "\n".join(
        [
            email.greeting.strip(),
            "",
            email.body.strip(),
            "",
            "Viele Grüße",
            *identification,
            "",
            "--",
            provenance,
            opt_out,
        ]
    )
