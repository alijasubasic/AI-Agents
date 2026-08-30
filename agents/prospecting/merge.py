"""Turning platform listings into one row per business.

The same roofer is "Alpenblick Dach & Fassade" on one platform and "Alpenblick
Dach und Fassade KG" on another, at the same address, with the same phone
number. Handing a salesperson both, as though they were two prospects, is how a
lead list loses its credibility on the first phone call.

Matching is deterministic and works on three keys, any one of which is enough:

    normalised name + postal code    "alpenblick dach fassade|81675"
    phone number in E.164            "+498955501234"
    website domain                   "alpenblick-dach.example"

Records sharing any key end up in the same group — a transitive union, so A
matching B on a phone number and B matching C on a domain puts all three
together. Nothing is fuzzy. Two businesses with similar names at different
addresses stay separate, which is the error worth avoiding: merging two real
companies loses one of them silently, while failing to merge shows up as an
obvious duplicate that a person can fix in a second.
"""

from __future__ import annotations

import re
import unicodedata

from agents.prospecting.extraction import (
    contacts_from_listing,
    contacts_from_page,
    normalise_phone,
    people_from_pages,
)
from agents.prospecting.models import (
    ContactPoint,
    ContactStatus,
    Lead,
    Listing,
    Person,
    Platform,
    WebPage,
    domain_of,
)

#: Legal forms and connectives that differ between platforms for the same firm.
_NOISE_WORDS = (
    "gmbh",
    "mbh",
    "ug",
    "haftungsbeschraenkt",
    "haftungsbeschrankt",
    "co",
    "kg",
    "ohg",
    "gbr",
    "ag",
    "se",
    "ek",
    "eg",
    "und",
    "and",
    "the",
)

#: Best status wins when the same detail arrives from several places.
_STATUS_RANK = {
    ContactStatus.CONFIRMED: 0,
    ContactStatus.REPORTED: 1,
    ContactStatus.CONSTRUCTED: 2,
    ContactStatus.INVALID: 3,
}


def fold(text: str) -> str:
    """Lowercase, transliterate, and reduce to alphanumerics and spaces.

    Umlauts become `ae`/`oe`/`ue` rather than losing the diaeresis, because that
    is the spelling platforms use when they cannot render one: "Müller" is
    written "Mueller" in half the directory entries in Germany and "Muller" in
    almost none.
    """
    lowered = text.lower().replace("&", " und ")
    for umlaut, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        lowered = lowered.replace(umlaut, replacement)

    folded = unicodedata.normalize("NFKD", lowered)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def normalise_name(name: str) -> str:
    """A company name with legal form and connectives removed."""
    words = [word for word in fold(name).split() if word not in _NOISE_WORDS]
    return " ".join(words)


def keys_for(listing: Listing) -> set[str]:
    """Every identity key a listing offers. More keys means more chances to match."""
    keys: set[str] = set()

    name = normalise_name(listing.name)
    if name:
        keys.add(f"name:{name}|{listing.postal_code.strip()}")

    number = normalise_phone(listing.phone_raw) if listing.phone_raw else None
    if number:
        keys.add(f"phone:{number}")

    if listing.website:
        domain = domain_of(listing.website)
        if domain:
            keys.add(f"domain:{domain}")

    return keys


def group_listings(listings: list[Listing]) -> list[list[Listing]]:
    """Group listings that describe the same business.

    Union-find over the shared keys. Groups come back in the order their first
    member was seen, so a run over the same input always produces the same lead
    ids — the demo and the eval suite both depend on that.
    """
    parent: dict[int, int] = {index: index for index in range(len(listings))}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            # Always attach the later record to the earlier one, so group
            # ordering follows first appearance rather than input length.
            first, second = sorted((left_root, right_root))
            parent[second] = first

    seen: dict[str, int] = {}
    for index, listing in enumerate(listings):
        for key in keys_for(listing):
            if key in seen:
                union(seen[key], index)
            else:
                seen[key] = index

    groups: dict[int, list[Listing]] = {}
    for index, listing in enumerate(listings):
        groups.setdefault(find(index), []).append(listing)

    return [groups[root] for root in sorted(groups)]


def _richest(listings: list[Listing]) -> Listing:
    """The listing with the most fields filled in, ties broken by platform order.

    Used for the canonical name and address. Google Maps tends to carry the
    trading name people recognise; the registry name on a directory entry is
    more correct and less useful on an envelope.
    """

    def score(listing: Listing) -> tuple[int, int]:
        filled = sum(
            bool(value)
            for value in (
                listing.street,
                listing.postal_code,
                listing.city,
                listing.website,
                listing.phone_raw,
                listing.name,
            )
        )
        return (-filled, list(Platform).index(listing.platform))

    return sorted(listings, key=score)[0]


def _dedupe_contacts(contacts: list[ContactPoint]) -> list[ContactPoint]:
    """One entry per distinct value, keeping the best-supported version.

    When the same address turns up in a directory and again in the imprint, the
    imprint version wins and the directory becomes a note on it — the detail is
    the same, but "they publish this themselves" is what decides whether it may
    be used.
    """
    best: dict[tuple[str, str], ContactPoint] = {}

    for contact in contacts:
        key = (contact.kind, contact.value)
        current = best.get(key)
        if current is None:
            best[key] = contact.model_copy(deep=True)
            continue

        if _STATUS_RANK[contact.status] < _STATUS_RANK[current.status]:
            replacement = contact.model_copy(deep=True)
            replacement.note = replacement.note or current.note
            best[key] = replacement
            current = replacement

        corroboration = f"also on {contact.platform.label}"
        if contact.platform is not current.platform and corroboration not in current.note:
            current.note = "; ".join(part for part in (current.note, corroboration) if part)

    return sorted(best.values(), key=lambda c: (c.kind, _STATUS_RANK[c.status], c.value))


def confidence_for(listings: list[Listing], contacts: list[ContactPoint]) -> float:
    """How sure we are this is a real, currently trading business.

    Corroboration is what moves this number: two platforms listing the same firm
    at the same address is much stronger evidence than one platform listing it
    twice as convincingly. Deliberately a formula rather than a model call —
    a confidence score that varies between runs cannot be tuned.
    """
    platforms = {listing.platform for listing in listings}
    score = 0.3 + 0.2 * len(platforms)

    if any(listing.website for listing in listings):
        score += 0.1
    if any(contact.contactable for contact in contacts):
        score += 0.15
    if any(contact.kind == "phone" for contact in contacts):
        score += 0.05

    return round(min(score, 1.0), 2)


def lead_id_for(name: str, postal_code: str, index: int) -> str:
    """A stable, readable id. The index keeps it unique when names collide."""
    slug = re.sub(r"\s+", "-", normalise_name(name)) or "lead"
    return f"lead-{index:02d}-{slug[:40]}-{postal_code or '00000'}"


def build_lead(
    listings: list[Listing],
    pages: list[WebPage],
    *,
    index: int,
) -> Lead:
    """Assemble one lead from every listing and page that belongs to it."""
    anchor = _richest(listings)
    website = next((listing.website for listing in listings if listing.website), "")
    business_domain = domain_of(website) if website else ""

    contacts: list[ContactPoint] = []
    for listing in listings:
        contacts.extend(contacts_from_listing(listing))
    for page in pages:
        contacts.extend(contacts_from_page(page, business_domain=business_domain or page.domain))

    people: list[Person] = people_from_pages(pages)
    categories: list[str] = []
    for listing in listings:
        categories.extend(category for category in listing.categories if category not in categories)

    merged = _dedupe_contacts(contacts)
    notes: list[str] = []
    if len(listings) > 1:
        found_on = ", ".join(sorted({listing.platform.label for listing in listings}))
        notes.append(f"{len(listings)} listings merged from {found_on}")

    return Lead(
        id=lead_id_for(anchor.name, anchor.postal_code, index),
        name=anchor.name,
        street=anchor.street,
        postal_code=anchor.postal_code,
        city=anchor.city,
        country=anchor.country,
        website=website,
        categories=categories,
        listings=listings,
        people=people,
        contacts=merged,
        confidence=confidence_for(listings, merged),
        notes=notes,
    )


def build_leads(
    listings: list[Listing],
    pages_by_domain: dict[str, list[WebPage]] | None = None,
) -> tuple[list[Lead], int]:
    """Merge listings into leads. Returns the leads and how many duplicates went.

    Pages are matched to a lead by the domain of its website, which is the only
    link that survives a business having three different names across three
    platforms.
    """
    pages_by_domain = pages_by_domain or {}
    groups = group_listings(listings)

    leads: list[Lead] = []
    for index, group in enumerate(groups, start=1):
        website = next((listing.website for listing in group if listing.website), "")
        pages = pages_by_domain.get(domain_of(website), []) if website else []
        leads.append(build_lead(group, pages, index=index))

    return leads, len(listings) - len(groups)
