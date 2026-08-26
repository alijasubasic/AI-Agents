"""Eval cases for the prospecting agent.

The scored properties are the ones a lead list lives or dies by: the same
business appears once, every contact detail is traceable to where it was
published, and a detail nobody published is never presented as one.
"""

from __future__ import annotations

from agents.prospecting.agent import ProspectingAgent
from agents.prospecting.extraction import extract_people, normalise_phone
from agents.prospecting.fixtures import AREA
from agents.prospecting.merge import group_listings, normalise_name
from agents.prospecting.models import (
    ContactStatus,
    Lead,
    Platform,
    ProspectingResult,
    SearchArea,
)
from agents.prospecting.providers import MockPages, MockPlaces
from agents.prospecting.scripted import provider_for
from core.config import Settings
from evals.models import Expectation, Layer, Score
from evals.registry import case
from evals.scoring import combine, equals, is_false, is_true, set_equals

AGENT = "prospecting"


def _find() -> ProspectingResult:
    return ProspectingAgent(
        places=[
            MockPlaces(Platform.GOOGLE_MAPS),
            MockPlaces(Platform.OPENSTREETMAP),
            MockPlaces(Platform.DIRECTORY),
        ],
        pages=MockPages(),
        provider=provider_for(AREA.what),
        settings=Settings(trace_enabled=False),
    ).find(AREA)


def _lead(name: str) -> Lead:
    return next(lead for lead in _find().leads if lead.name == name)


# --- Merging ------------------------------------------------------------


@case(
    id="prospecting-one-row-per-business",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Ten listings across three platforms become five businesses.",
)
def _() -> Score:
    found = _find()
    return combine(
        equals(len(found.leads), 5, label="leads"),
        equals(found.duplicates_merged, 4, label="duplicates merged"),
    )


@case(
    id="prospecting-three-spellings-merge",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The same firm under three names on three platforms is one lead.",
)
def _() -> Score:
    lead = _lead("Alpenblick Dach & Fassade")
    return set_equals(
        lead.platforms,
        [Platform.GOOGLE_MAPS, Platform.OPENSTREETMAP, Platform.DIRECTORY],
        label="platforms",
    )


@case(
    id="prospecting-legal-form-is-not-identity",
    agent=AGENT,
    layer=Layer.LOGIC,
    description='"Dach & Fassade" and "Dach und Fassade KG" are the same name.',
)
def _() -> Score:
    return equals(
        normalise_name("Alpenblick Dach und Fassade KG"),
        normalise_name("Alpenblick Dach & Fassade"),
        label="normalised name",
    )


@case(
    id="prospecting-different-towns-stay-separate",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Two firms with the same name at different postcodes are not merged.",
)
def _() -> Score:
    from agents.prospecting.models import Listing

    groups = group_listings(
        [
            Listing(
                platform=Platform.GOOGLE_MAPS,
                platform_id="a",
                name="Dach GmbH",
                postal_code="80337",
            ),
            Listing(
                platform=Platform.DIRECTORY,
                platform_id="b",
                name="Dach GmbH",
                postal_code="81669",
            ),
        ]
    )
    return equals(len(groups), 2, label="groups")


# --- Provenance ---------------------------------------------------------


@case(
    id="prospecting-every-detail-has-a-source",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Every email address and phone number carries the URL it came from.",
)
def _() -> Score:
    contacts = [contact for lead in _find().leads for contact in lead.contacts]
    missing = [contact.value for contact in contacts if not contact.source_url]
    return is_true(not missing, label=f"all {len(contacts)} details sourced")


@case(
    id="prospecting-imprint-address-is-confirmed",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An address on the business's own imprint is CONFIRMED and usable.",
)
def _() -> Score:
    best = _lead("Reiter Bedachungen GmbH").best_email()
    return combine(
        equals(
            best.value if best else None,
            "m.reiter@reiter-bedachungen.example",
            label="address",
        ),
        equals(best.status if best else None, ContactStatus.CONFIRMED, label="status"),
    )


@case(
    id="prospecting-web-agency-is-not-the-business",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An address on a different domain never becomes CONFIRMED.",
)
def _() -> Score:
    lead = _lead("Reiter Bedachungen GmbH")
    agency = next(c for c in lead.emails if c.value == "kontakt@studio-nordlicht.example")
    return equals(agency.status, ContactStatus.REPORTED, label="status")


@case(
    id="prospecting-directory-address-is-only-reported",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A directory entry is not a publication by the business itself.",
)
def _() -> Score:
    lead = _lead("Alpenblick Dach & Fassade")
    return combine(
        equals([c.status for c in lead.emails], [ContactStatus.REPORTED], label="statuses"),
        is_false(lead.is_contactable, label="contactable"),
    )


@case(
    id="prospecting-guess-is-labelled-not-promoted",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A pattern-built address is kept, labelled, and never returned as usable.",
)
def _() -> Score:
    lead = _lead("Dachdeckerei Sailer & Sohn")
    guesses = [c for c in lead.emails if c.status is ContactStatus.CONSTRUCTED]
    return combine(
        equals([c.value for c in guesses], ["s.sailer@sailer-dach.example"], label="guess"),
        equals(lead.best_email(), None, label="best email"),
    )


@case(
    id="prospecting-no-reply-is-not-a-contact",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A no-reply mailbox is marked INVALID rather than offered as an address.",
)
def _() -> Score:
    lead = _lead("Nordwind Dachtechnik GmbH")
    noreply = next(c for c in lead.emails if c.value.startswith("noreply@"))
    return equals(noreply.status, ContactStatus.INVALID, label="status")


# --- Extraction ---------------------------------------------------------


@case(
    id="prospecting-name-does-not-absorb-the-next-line",
    agent=AGENT,
    layer=Layer.LOGIC,
    description='"Inhaber: Stefan Sailer" followed by "Telefon:" yields one person.',
)
def _() -> Score:
    people = extract_people("Inhaber: Stefan Sailer\nTelefon: 089 5550 8877\n")
    return equals([p.name for p in people], ["Stefan Sailer"], label="people")


@case(
    id="prospecting-ambiguous-number-is-refused",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A number with no country prefix and no national zero is dropped.",
)
def _() -> Score:
    return combine(
        equals(normalise_phone("089/5550-1234"), "+498955501234", label="national number"),
        equals(normalise_phone("5550 123"), None, label="ambiguous number"),
    )


@case(
    id="prospecting-portal-is-excluded",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A comparison portal matching the trade is filtered out by the plan.",
)
def _() -> Score:
    names = " ".join(lead.name for lead in _find().leads)
    return is_false("Vergleich24" in names, label="portal in results")


@case(
    id="prospecting-run-is-reproducible",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The same area searched twice produces the same leads in the same order.",
)
def _() -> Score:
    return equals(
        [lead.id for lead in _find().leads],
        [lead.id for lead in _find().leads],
        label="lead ids",
    )


# --- Known gaps ---------------------------------------------------------


@case(
    id="prospecting-contact-form-is-a-dead-end",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A business that publishes only a contact form yields an address.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Nothing here fills in a form, and a form is what a large share of German "
        "small businesses put where an address would be — deliberately, to stop "
        "exactly this kind of collection. Those firms stay reachable by phone "
        "only, and the export says so rather than inventing a way in."
    ),
)
def _() -> Score:
    return is_true(
        _lead("Dachdeckerei Sailer & Sohn").is_contactable,
        label="contactable via the contact form",
    )


@case(
    id="prospecting-trade-without-an-osm-mapping",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Every trade maps to the OpenStreetMap tag that describes it.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "OSM_TAG_HINTS covers about twenty trades. Anything else falls back to a "
        "name search, which finds only businesses with the trade in their name — "
        "far fewer, though never the wrong kind. Extending the table is work "
        "somebody has to do per trade, and guessing at it would return the wrong "
        "businesses confidently."
    ),
)
def _() -> Score:
    from agents.prospecting.providers import OverpassProvider

    query = OverpassProvider().build_query(
        SearchArea(what="Fliesenleger", where="München"), "Fliesenleger München"
    )
    return is_true("craft" in query, label="tag-based query")
