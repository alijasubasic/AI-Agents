"""Pulling names, addresses and numbers out of text, deterministically.

No model is involved anywhere in this module, and that is the design. A model
asked for "the email address on this page" will produce one whether or not the
page contains it, and the invented address is indistinguishable from the real
one right up until the mail bounces — or worse, until it does not, because the
guess happened to land on a stranger's mailbox.

So extraction is regular expressions over retrieved text, and every result
carries the URL it came from. Three rules do most of the work:

1. An address published on the business's own domain is `CONFIRMED`. The same
   address found anywhere else is `REPORTED`.
2. An address whose domain is not the business's own is never `CONFIRMED`, even
   when it appears on their site — the footer credit of the agency that built
   the website is the classic example.
3. An address nobody published is `CONSTRUCTED`, and is kept only so that the
   rest of the system can refuse to write to it.
"""

from __future__ import annotations

import re
import unicodedata

from agents.prospecting.models import (
    ContactPoint,
    ContactStatus,
    Listing,
    Person,
    Platform,
    WebPage,
    domain_of,
)

#: The default country for numbers written without an international prefix.
#: Germany, because that is the market this repository's fixtures describe.
DEFAULT_COUNTRY_CODE = "49"

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

#: Obfuscations that survive a copy-paste from a rendered page. Every one of
#: these appears on real German imprints trying to slow down scrapers.
_DEOBFUSCATION = (
    (re.compile(r"\s*[\(\[\{]\s*(?:at|ät)\s*[\)\]\}]\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s+(?:at|ät)\s+", re.IGNORECASE), "@"),
    (re.compile(r"\s*[\(\[\{]\s*(?:dot|punkt)\s*[\)\]\}]\s*", re.IGNORECASE), "."),
    (re.compile(r"\s+(?:dot|punkt)\s+", re.IGNORECASE), "."),
)

#: Local parts that accept no mail, or exist to catch scrapers.
_UNDELIVERABLE = ("noreply", "no-reply", "donotreply", "do-not-reply", "spamtrap")

_PHONE_LABEL = r"(?:tel(?:efon)?|fon|ruf(?:nummer)?|mobil|handy|phone|t)"
_PHONE_BODY = r"[\d][\d\s()/.–—-]{5,24}\d"

_LABELLED_PHONE_RE = re.compile(
    rf"{_PHONE_LABEL}\s*[.:]?\s*(?P<number>(?:\+\s?\d{{1,3}}\s?)?\(?\d\)?{_PHONE_BODY})",
    re.IGNORECASE,
)
_INTERNATIONAL_PHONE_RE = re.compile(rf"(?P<number>\+\s?\d{{1,3}}[\s/.-]?{_PHONE_BODY})")

#: Roles a German imprint prints next to the person who is legally responsible.
_ROLES = (
    "geschäftsführerin",
    "geschäftsführer",
    "geschäftsleitung",
    "inhaberin",
    "inhaber",
    "prokuristin",
    "prokurist",
    "ansprechpartnerin",
    "ansprechpartner",
    "betriebsleiterin",
    "betriebsleiter",
    "vertreten durch",
    "verantwortlich",
)
_ROLE_ALTERNATION = "|".join(_ROLES)

#: Academic and professional titles that precede a name without being part of it.
_TITLES = ("dipl.-ing.", "dipl.-kfm.", "dr.", "prof.", "ing.", "m.sc.", "b.sc.", "meister")

#: Names are matched with space-only separators and one line at a time. `\s`
#: would cross a line break, and on a real imprint the line after the managing
#: director's name is "Telefon: …" — which is how "Stefan Sailer Telefon"
#: becomes a person, and then an email address addressed to them.
#: Titles sit in front of a name and are stripped from it afterwards. Matched
#: here so that "Geschäftsführer: Dr. Martin Reiter" finds a person at all —
#: without this the name pattern starts at "Martin" and the match fails on the
#: separator before it.
_TITLE_PREFIX = r"(?:(?:Dr|Prof|Dipl|Ing|B\.?Sc|M\.?Sc)\.?(?:-[A-ZÄÖÜ][\wäöüß]+\.?)?[ \t]+){0,2}"

_NAME = _TITLE_PREFIX + r"(?:[A-ZÄÖÜ][\wÄÖÜäöüß'’-]+[ \t]+){1,3}[A-ZÄÖÜ][\wÄÖÜäöüß'’-]+"

#: Words that are never part of a person's name, however capitalised they are.
_NOT_A_NAME = frozenset(
    {
        "telefon",
        "telefax",
        "fax",
        "mobil",
        "handy",
        "email",
        "e-mail",
        "mail",
        "web",
        "website",
        "internet",
        "impressum",
        "kontakt",
        "adresse",
        "anschrift",
        "sitz",
        "team",
        "registergericht",
        "handelsregister",
        "umsatzsteuer",
        "ust",
        "gmbh",
        "kg",
        "ohg",
        "gbr",
        "ag",
        "die",
        "der",
        "das",
    }
)

_ROLE_FIRST_RE = re.compile(
    rf"(?P<role>{_ROLE_ALTERNATION})\s*(?:\(in\))?\s*[:\-–—]?\s*(?P<name>{_NAME})",
    re.IGNORECASE,
)
_NAME_FIRST_RE = re.compile(
    rf"(?P<name>{_NAME})\s*[,–—-]\s*(?P<role>{_ROLE_ALTERNATION})",
    re.IGNORECASE,
)


# --- Email --------------------------------------------------------------


def deobfuscate(text: str) -> str:
    """Turn `info (at) example de` back into something an address regex can see."""
    for pattern, replacement in _DEOBFUSCATION:
        text = pattern.sub(replacement, text)
    return text


def normalise_email(raw: str) -> str | None:
    """Lowercase and validate one address. None if it is not one."""
    candidate = deobfuscate(raw).strip().strip("<>,;:").lower()
    match = _EMAIL_RE.fullmatch(candidate)
    return match.group(0) if match else None


def is_undeliverable(address: str) -> bool:
    """Whether this address exists specifically to not receive mail."""
    local = address.split("@", 1)[0]
    return any(marker in local for marker in _UNDELIVERABLE)


def extract_emails(text: str) -> list[str]:
    """Every distinct address in a block of text, in the order they appear."""
    found: dict[str, None] = {}
    for match in _EMAIL_RE.finditer(deobfuscate(text)):
        address = match.group(0).lower().rstrip(".")
        found.setdefault(address, None)
    return list(found)


# --- Phone --------------------------------------------------------------


def normalise_phone(raw: str, *, country_code: str = DEFAULT_COUNTRY_CODE) -> str | None:
    """Convert a written number into E.164, or None if it cannot be trusted.

    A number with no country prefix and no leading national zero is rejected
    rather than guessed at. "5550 123" could be a local number, an extension or
    a house number, and a lead file full of numbers that dial nowhere is worse
    than one with gaps in it.
    """
    cleaned = re.sub(r"[^\d+]", "", raw.replace("(0)", ""))

    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif cleaned.startswith("+"):
        pass
    elif cleaned.startswith("0"):
        cleaned = "+" + country_code + cleaned[1:]
    else:
        return None

    digits = cleaned[1:]
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def extract_phones(text: str, *, country_code: str = DEFAULT_COUNTRY_CODE) -> list[tuple[str, str]]:
    """Find phone numbers and the label they were printed under.

    Returns `(e164, label)` pairs. Fax lines are skipped: a fax number in a
    field called `phone` is a wrong number that looks like a right one.
    """
    found: dict[str, str] = {}

    for line in text.splitlines():
        lowered = line.lower()
        if "fax" in lowered:
            continue

        label = "Mobil" if ("mobil" in lowered or "handy" in lowered) else "Telefon"
        for pattern in (_LABELLED_PHONE_RE, _INTERNATIONAL_PHONE_RE):
            for match in pattern.finditer(line):
                number = normalise_phone(match.group("number"), country_code=country_code)
                if number:
                    found.setdefault(number, label)

    return list(found.items())


# --- People -------------------------------------------------------------


def _clean_name(raw: str) -> str:
    """Strip titles and stray punctuation from a captured name."""
    name = " ".join(raw.split()).strip(" ,;:-–—")
    words = name.split()
    while words and words[0].lower().rstrip(",") in _TITLES:
        words.pop(0)
    return " ".join(words)


def _is_plausible_name(name: str) -> bool:
    """Two or more words, none of which is a form label or a legal form."""
    words = name.split()
    return len(words) >= 2 and not any(word.lower().strip(".:,") in _NOT_A_NAME for word in words)


def extract_people(text: str, *, source_url: str = "") -> list[Person]:
    """Find named people and the role printed beside them.

    Both orders are handled, because German pages use both: "Geschäftsführer:
    Martin Reiter" and "Martin Reiter, Geschäftsführer". Matching runs per line,
    so a role at the end of one line cannot capture the label at the start of
    the next.
    """
    people: dict[str, Person] = {}

    for line in text.splitlines():
        for pattern in (_ROLE_FIRST_RE, _NAME_FIRST_RE):
            for match in pattern.finditer(line):
                name = _clean_name(match.group("name"))
                if not _is_plausible_name(name):
                    continue

                role = " ".join(match.group("role").split()).title()
                people.setdefault(
                    name.lower(),
                    Person(name=name, role=role, source_url=source_url),
                )

    return list(people.values())


def _tokens(name: str, *, transliterate: bool = True) -> list[str]:
    """Lowercase, folded name parts, for matching against a local part.

    Two foldings exist because German mailboxes use both: `Müller` is
    `mueller@` about as often as `muller@`, and a match on only one of them
    silently drops half the personal addresses on any real domain.
    """
    lowered = name.lower()
    if transliterate:
        for umlaut, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
            lowered = lowered.replace(umlaut, replacement)
    lowered = lowered.replace("ß", "ss")

    folded = unicodedata.normalize("NFKD", lowered)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return [part for part in re.split(r"[^a-z]+", folded) if part]


def attribute_email(address: str, people: list[Person]) -> Person | None:
    """Match `m.reiter@…` to Martin Reiter, and refuse to match anything looser.

    The local part must contain the surname, or the initial-plus-surname form.
    `info@` matches nobody, and neither does a first name on its own — too many
    firms have two Michaels.
    """
    local = address.split("@", 1)[0]
    parts = [part for part in re.split(r"[^a-z0-9]+", local.lower()) if part]
    if not parts:
        return None

    for person in people:
        for tokens in (_tokens(person.name), _tokens(person.name, transliterate=False)):
            if len(tokens) < 2:
                continue
            first, last = tokens[0], tokens[-1]

            if last in parts:
                return person
            # m.reiter / mreiter, written as one token
            if any(part in (f"{first[0]}{last}", f"{last}{first[0]}") for part in parts):
                return person
            if len(parts) >= 2 and parts[0] == first[0] and parts[1] == last:
                return person

    return None


def construct_email(person: Person, domain: str) -> ContactPoint | None:
    """Build the address this person *probably* has, and label it as a guess.

    This exists so the guess can be shown to a human, never so it can be
    written to. `ContactStatus.CONSTRUCTED` fails the outreach policy and codex
    article A9; the demo includes a lead whose only address is one of these,
    precisely so that path runs.
    """
    tokens = _tokens(person.name)
    if len(tokens) < 2 or not domain:
        return None

    address = f"{tokens[0][0]}.{tokens[-1]}@{domain}"
    return ContactPoint(
        kind="email",
        value=address,
        raw=address,
        status=ContactStatus.CONSTRUCTED,
        platform=Platform.WEBSITE,
        source_url=person.source_url,
        person=person.name,
        role=person.role,
        note=f"pattern guess from {person.name}; never published anywhere",
    )


# --- Whole records ------------------------------------------------------


def contacts_from_listing(listing: Listing) -> list[ContactPoint]:
    """Contact details a platform handed over with its listing.

    Everything here is `REPORTED`. A map or directory entry can be years old and
    is often maintained by someone other than the business, so it is good enough
    to call and not good enough to write to unattended.
    """
    contacts: list[ContactPoint] = []

    address = normalise_email(listing.email_raw) if listing.email_raw else None
    if address:
        contacts.append(
            ContactPoint(
                kind="email",
                value=address,
                raw=listing.email_raw,
                status=(
                    ContactStatus.INVALID if is_undeliverable(address) else ContactStatus.REPORTED
                ),
                platform=listing.platform,
                source_url=listing.source_url,
                found_on=listing.platform.label,
                note="" if not is_undeliverable(address) else "no-reply address",
            )
        )

    number = normalise_phone(listing.phone_raw) if listing.phone_raw else None
    if number:
        contacts.append(
            ContactPoint(
                kind="phone",
                value=number,
                raw=listing.phone_raw,
                status=ContactStatus.REPORTED,
                platform=listing.platform,
                source_url=listing.source_url,
                found_on=listing.platform.label,
            )
        )

    return contacts


def contacts_from_page(page: WebPage, *, business_domain: str = "") -> list[ContactPoint]:
    """Contact details the business published itself.

    An address on the business's own domain is `CONFIRMED`. One on a different
    domain is `REPORTED` with the reason attached — usually the web agency in
    the footer, occasionally a landlord or a parent company, never someone this
    system may cold-mail as though the business had published it.
    """
    own_domain = (business_domain or page.domain).lower()
    people = extract_people(page.text, source_url=page.url)
    found_on = page.kind if page.kind != "other" else "Website"
    contacts: list[ContactPoint] = []

    for address in extract_emails(page.text):
        person = attribute_email(address, people)
        note = ""

        if is_undeliverable(address):
            status = ContactStatus.INVALID
            note = "no-reply address"
        elif own_domain and domain_of(address) != own_domain:
            status = ContactStatus.REPORTED
            note = f"published on {own_domain} but belongs to {domain_of(address)}"
        else:
            status = ContactStatus.CONFIRMED

        contacts.append(
            ContactPoint(
                kind="email",
                value=address,
                raw=address,
                status=status,
                platform=Platform.WEBSITE,
                source_url=page.url,
                found_on=found_on,
                person=person.name if person else None,
                role=person.role if person else None,
                note=note,
            )
        )

    for number, label in extract_phones(page.text):
        contacts.append(
            ContactPoint(
                kind="phone",
                value=number,
                raw=number,
                status=ContactStatus.CONFIRMED,
                platform=Platform.WEBSITE,
                source_url=page.url,
                found_on=f"{found_on} ({label})",
            )
        )

    return contacts


def people_from_pages(pages: list[WebPage]) -> list[Person]:
    """Every person named across a site, with their own address if there is one.

    A person is only given an email when one on the page attributes itself to
    them. Nothing is constructed here — that is `construct_email`'s job, and it
    is called explicitly by a caller who wants a guess and knows it is one.
    """
    people: dict[str, Person] = {}

    for page in pages:
        page_contacts = contacts_from_page(page, business_domain=page.domain)
        for person in extract_people(page.text, source_url=page.url):
            existing = people.get(person.name.lower())
            if existing is None:
                people[person.name.lower()] = person
                existing = person
            elif not existing.role and person.role:
                existing.role = person.role

            for contact in page_contacts:
                if contact.person != existing.name:
                    continue
                if contact.kind == "email" and existing.email is None:
                    existing.email = contact.value
                    existing.status = contact.status
                elif contact.kind == "phone" and existing.phone is None:
                    existing.phone = contact.value

    return list(people.values())
