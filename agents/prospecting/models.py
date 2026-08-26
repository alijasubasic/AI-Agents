"""Data models for area prospecting.

The split mirrors the rest of the repository: what a **platform** said, what the
**system** made of it, and how much each of those is worth.

* :class:`Listing` is one platform's raw record of one business. It is never
  edited — a Google Maps result and an OpenStreetMap result stay separate
  objects even when they describe the same roofer.
* :class:`Lead` is what merging several listings produced, with every listing it
  came from still attached.
* :class:`ContactPoint` is a single email address or phone number *plus where it
  was found*. That provenance is the whole point: an address printed in a
  company's own imprint and an address a pattern generator invented look
  identical as strings, and only one of them may be written to.

Nothing in this package decides whether a lead may be contacted. That decision
belongs to `agents/outreach/policy.py` and to the codex, both of which read
:attr:`ContactPoint.status`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Platform(StrEnum):
    """Where a record came from."""

    GOOGLE_MAPS = "google_maps"
    OPENSTREETMAP = "openstreetmap"
    DIRECTORY = "directory"
    WEBSITE = "website"

    @property
    def label(self) -> str:
        return {
            Platform.GOOGLE_MAPS: "Google Maps",
            Platform.OPENSTREETMAP: "OpenStreetMap",
            Platform.DIRECTORY: "Branchenbuch",
            Platform.WEBSITE: "Firmenwebsite",
        }.get(self, self.value)


class ContactStatus(StrEnum):
    """How much a contact detail is worth.

    The ordering of the members is not meaningful; the distinction between the
    first member and the rest is. `CONFIRMED` is the only status that may be
    written to, and it means one specific thing: the business published this
    detail itself, on its own domain.
    """

    #: Published by the business on its own website (imprint, contact, team).
    CONFIRMED = "confirmed"
    #: A third party says so — a directory entry, a map listing, a footer.
    REPORTED = "reported"
    #: Derived from a naming pattern. A guess wearing the costume of a fact.
    CONSTRUCTED = "constructed"
    #: Failed a syntax or plausibility check, or is a known no-reply address.
    INVALID = "invalid"

    @property
    def contactable(self) -> bool:
        return self is ContactStatus.CONFIRMED


class SearchArea(BaseModel):
    """What to look for, and where.

    `radius_km` is advisory: the platforms interpret proximity differently, and
    OpenStreetMap has no notion of "near" at all without a bounding box. It is
    passed to whichever provider can use it and recorded either way, so a result
    set can be reproduced later.
    """

    what: str = Field(description='The trade or category, e.g. "Dachdecker".')
    where: str = Field(description='The place, e.g. "München" or "Landkreis Rosenheim".')
    radius_km: float = Field(default=15.0, gt=0, le=200)
    country: str = "DE"
    limit: int = Field(default=25, ge=1, le=200)

    def describe(self) -> str:
        return f"{self.what} in {self.where} ({self.radius_km:.0f} km, max {self.limit})"


class SearchPlan(BaseModel):
    """The model's plan for one area.

    This is the only judgement the model contributes to finding businesses: how
    to phrase the queries. Every fact about every business comes from a
    provider, never from the plan.
    """

    queries: list[str] = Field(
        description=(
            "Two to five search phrases for the platforms, in the language of "
            "the target country. Include the trade, obvious synonyms for it, and "
            "the place. Do not invent company names."
        )
    )
    categories: list[str] = Field(
        default_factory=list,
        description="Platform category names that match this trade, if you know them.",
    )
    exclude_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Words that indicate a hit is the wrong kind of business — "
            "wholesalers, portals, comparison sites."
        ),
    )
    rationale: str = Field(default="", description="One sentence on why these queries.")


class Listing(BaseModel):
    """One platform's record of one business, as retrieved."""

    platform: Platform
    platform_id: str
    name: str

    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = "DE"

    latitude: float | None = None
    longitude: float | None = None

    phone_raw: str = ""
    email_raw: str = ""
    website: str = ""

    categories: list[str] = Field(default_factory=list)
    rating: float | None = None
    review_count: int | None = None

    source_url: str = ""
    retrieved_at: datetime | None = None

    @property
    def address(self) -> str:
        parts = [self.street, f"{self.postal_code} {self.city}".strip()]
        return ", ".join(part for part in parts if part)


class WebPage(BaseModel):
    """A page from a business's own site, already reduced to text.

    `kind` matters for extraction: a name on a team page is an employee, a name
    in an imprint is legally the person responsible, and German imprints follow
    a shape regular expressions can exploit.
    """

    url: str
    kind: Literal["home", "impressum", "kontakt", "team", "other"] = "other"
    text: str

    @property
    def domain(self) -> str:
        return domain_of(self.url)


class Person(BaseModel):
    """Someone at the business, with the role that was printed next to them."""

    name: str
    role: str = ""
    email: str | None = None
    phone: str | None = None
    source_url: str = ""
    status: ContactStatus = ContactStatus.REPORTED

    @property
    def label(self) -> str:
        return f"{self.name} ({self.role})" if self.role else self.name


class ContactPoint(BaseModel):
    """One email address or phone number, and where it was found."""

    kind: Literal["email", "phone"]
    value: str = Field(description="Normalised: lowercased address, or E.164 number.")
    raw: str = ""
    status: ContactStatus
    platform: Platform
    source_url: str = ""
    found_on: str = ""
    person: str | None = None
    role: str | None = None
    note: str = ""

    @property
    def contactable(self) -> bool:
        return self.status.contactable

    @property
    def is_role_address(self) -> bool:
        """Whether this is a shared mailbox (info@, kontakt@) rather than a person."""
        return self.kind == "email" and self.value.split("@", 1)[0] in ROLE_MAILBOXES


#: Local parts that belong to a function rather than a person. Writing to one is
#: fine; addressing it as though it were a person is not.
ROLE_MAILBOXES = frozenset(
    {
        "info",
        "kontakt",
        "contact",
        "office",
        "buero",
        "büro",
        "mail",
        "email",
        "post",
        "service",
        "anfrage",
        "hello",
        "hallo",
        "sekretariat",
        "verwaltung",
    }
)


class Lead(BaseModel):
    """One business, assembled from every platform that mentioned it."""

    id: str
    name: str

    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = "DE"
    website: str = ""

    categories: list[str] = Field(default_factory=list)
    listings: list[Listing] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    contacts: list[ContactPoint] = Field(default_factory=list)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)

    # -- addresses and numbers -------------------------------------------

    @property
    def address(self) -> str:
        parts = [self.street, f"{self.postal_code} {self.city}".strip()]
        return ", ".join(part for part in parts if part)

    @property
    def emails(self) -> list[ContactPoint]:
        return [c for c in self.contacts if c.kind == "email"]

    @property
    def phones(self) -> list[ContactPoint]:
        return [c for c in self.contacts if c.kind == "phone"]

    @property
    def platforms(self) -> list[Platform]:
        """Every platform that contributed something, in a stable order."""
        seen = {listing.platform for listing in self.listings}
        seen.update(contact.platform for contact in self.contacts)
        return [platform for platform in Platform if platform in seen]

    def best_email(self) -> ContactPoint | None:
        """The address most worth writing to, or None if there is none.

        Preference order: a confirmed personal address, then a confirmed role
        mailbox, then nothing. Reported and constructed addresses are never
        returned — a caller that wants one has to go looking in `emails`, which
        is exactly the friction that belongs in front of that decision.
        """
        confirmed = [c for c in self.emails if c.contactable]
        personal = [c for c in confirmed if not c.is_role_address]
        return (personal or confirmed or [None])[0]

    def best_phone(self) -> ContactPoint | None:
        """The most trustworthy number, confirmed first, then reported.

        A mobile number is used only when there is no other. It is usually one
        person's private handset rather than the business's line, and a lead
        export that hands out the owner's mobile by default is a lead export
        that gets a business annoyed with you before the first sentence.
        """
        valid = [c for c in self.phones if c.status is not ContactStatus.INVALID]
        ranked = sorted(
            valid,
            key=lambda c: (0 if c.contactable else 1, 1 if "mobil" in c.found_on.lower() else 0),
        )
        return ranked[0] if ranked else None

    def primary_person(self) -> Person | None:
        """The person to address, preferring one with their own email."""
        if not self.people:
            return None
        with_email = [p for p in self.people if p.email]
        return (with_email or self.people)[0]

    # -- what a salesperson actually asks --------------------------------

    @property
    def is_contactable(self) -> bool:
        """Whether there is an address this system is willing to write to."""
        return self.best_email() is not None

    @property
    def completeness(self) -> float:
        """How much of name / person / email / phone this lead actually has."""
        have = [
            bool(self.name),
            self.primary_person() is not None,
            self.best_email() is not None,
            self.best_phone() is not None,
        ]
        return sum(have) / len(have)

    @property
    def missing(self) -> list[str]:
        """The fields a salesperson would have to fill in by hand."""
        gaps = []
        if self.primary_person() is None:
            gaps.append("Ansprechpartner")
        if self.best_email() is None:
            gaps.append("E-Mail")
        if self.best_phone() is None:
            gaps.append("Telefon")
        return gaps


class ProspectingResult(BaseModel):
    """Everything one area search produced."""

    area: SearchArea
    plan: SearchPlan | None = None
    leads: list[Lead] = Field(default_factory=list)

    listings_seen: int = 0
    duplicates_merged: int = 0
    pages_read: int = 0

    cost_usd: float = 0.0
    duration_ms: float = 0.0
    halted_reason: str | None = None

    @property
    def contactable(self) -> list[Lead]:
        return [lead for lead in self.leads if lead.is_contactable]

    @property
    def with_phone(self) -> list[Lead]:
        return [lead for lead in self.leads if lead.best_phone() is not None]

    @property
    def with_person(self) -> list[Lead]:
        return [lead for lead in self.leads if lead.primary_person() is not None]


def domain_of(url_or_email: str) -> str:
    """The bare domain of a URL or an email address, lowercased.

    Deliberately not `urllib.parse`: half the values reaching this function are
    email addresses, and the other half are URLs typed by hand into a map
    listing, with and without a scheme.
    """
    value = url_or_email.strip().lower()
    if "@" in value:
        return value.rsplit("@", 1)[-1].strip("/")

    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break

    value = value.split("/", 1)[0].split("?", 1)[0]
    return value[4:] if value.startswith("www.") else value
