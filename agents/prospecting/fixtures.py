"""Synthetic listings and pages for one area: roofers in Munich.

Invented, like every other fixture in this repository. The domains are all
`.example`, which is reserved by RFC 2606 and can never resolve, and the phone
numbers all sit in the 5550 block that exists for exactly this purpose. Nothing
here describes a real business, and no real business's data has ever been in
this repository.

The set is built so every path through the pipeline runs at least once:

    Reiter Bedachungen     two platforms merge; imprint and team page give a
                           confirmed personal address -> contactable
    Sailer & Sohn          merges by phone number alone; the site has a contact
                           form and no address, so the only email is a
                           construction -> blocked before it is ever sent
    Alpenblick             three platforms, three spellings of the name; the
                           only address comes from a directory -> reported, so
                           a person decides
    Bauzentrum Isartal     a role mailbox and nobody named -> contactable, but
                           the brief says the name is missing
    Nordwind Dachtechnik   fully contactable and on the suppression list, so
                           the outreach policy stops it anyway
    Vergleich24            a comparison portal, not a roofer -> excluded by the
                           plan's exclusion terms
"""

from __future__ import annotations

from datetime import UTC, datetime

from agents.prospecting.models import Listing, Platform, SearchArea, WebPage

#: Fixed so the demo, the tests and the eval suite all see the same run.
REFERENCE_NOW = datetime(2026, 3, 5, 9, 0, tzinfo=UTC)

AREA = SearchArea(what="Dachdecker", where="München", radius_km=20.0, limit=25)


def _listing(**kwargs) -> Listing:
    return Listing(retrieved_at=REFERENCE_NOW, **kwargs)


# --- Google Maps --------------------------------------------------------

MAPS_LISTINGS: list[Listing] = [
    _listing(
        platform=Platform.GOOGLE_MAPS,
        platform_id="places/ChIJfixture01",
        name="Reiter Bedachungen GmbH",
        street="Lindwurmstraße 112",
        postal_code="80337",
        city="München",
        latitude=48.1247,
        longitude=11.5541,
        phone_raw="089 5550 1234",
        website="https://reiter-bedachungen.example",
        categories=["Dachdecker", "Bauunternehmen"],
        rating=4.6,
        review_count=38,
        source_url="https://maps.google.com/?cid=fixture01",
    ),
    _listing(
        platform=Platform.GOOGLE_MAPS,
        platform_id="places/ChIJfixture02",
        name="Dachdeckerei Sailer & Sohn",
        street="Baaderstraße 9",
        postal_code="80469",
        city="München",
        latitude=48.1298,
        longitude=11.5789,
        phone_raw="089 5550 8877",
        website="https://sailer-dach.example",
        categories=["Dachdecker"],
        rating=4.9,
        review_count=12,
        source_url="https://maps.google.com/?cid=fixture02",
    ),
    _listing(
        platform=Platform.GOOGLE_MAPS,
        platform_id="places/ChIJfixture03",
        name="Alpenblick Dach & Fassade",
        street="Rosenheimer Str. 45",
        postal_code="81669",
        city="München",
        phone_raw="089 5550 4410",
        categories=["Dachdecker", "Fassadenbau"],
        rating=4.1,
        review_count=57,
        source_url="https://maps.google.com/?cid=fixture03",
    ),
    _listing(
        platform=Platform.GOOGLE_MAPS,
        platform_id="places/ChIJfixture04",
        name="Bauzentrum Isartal e.K.",
        street="Isartalstraße 30",
        postal_code="80469",
        city="München",
        phone_raw="089 5550 2201",
        website="https://bauzentrum-isartal.example",
        categories=["Dachdecker", "Spenglerei"],
        rating=4.3,
        review_count=21,
        source_url="https://maps.google.com/?cid=fixture04",
    ),
    _listing(
        platform=Platform.GOOGLE_MAPS,
        platform_id="places/ChIJfixture05",
        name="Nordwind Dachtechnik GmbH",
        street="Schleißheimer Str. 210",
        postal_code="80797",
        city="München",
        phone_raw="+49 89 5550 6600",
        website="https://nordwind-dachtechnik.example",
        categories=["Dachdecker", "Flachdach"],
        rating=4.8,
        review_count=64,
        source_url="https://maps.google.com/?cid=fixture05",
    ),
]

# --- OpenStreetMap ------------------------------------------------------

OSM_LISTINGS: list[Listing] = [
    _listing(
        platform=Platform.OPENSTREETMAP,
        platform_id="node/4411002201",
        name="Reiter Bedachungen",
        street="Lindwurmstraße 112",
        postal_code="80337",
        city="München",
        latitude=48.1247,
        longitude=11.5541,
        phone_raw="+49 89 55501234",
        website="https://reiter-bedachungen.example",
        categories=["craft=roofer"],
        source_url="https://www.openstreetmap.org/node/4411002201",
    ),
    _listing(
        platform=Platform.OPENSTREETMAP,
        platform_id="node/4411002314",
        name="Alpenblick Dach und Fassade KG",
        street="Rosenheimer Straße 45",
        postal_code="81669",
        city="München",
        phone_raw="+49 89 55504410",
        categories=["craft=roofer", "craft=plasterer"],
        source_url="https://www.openstreetmap.org/node/4411002314",
    ),
]

# --- Branchenbuch / directory ------------------------------------------

DIRECTORY_LISTINGS: list[Listing] = [
    _listing(
        platform=Platform.DIRECTORY,
        platform_id="branchen/muenchen/sailer-sohn",
        name="Sailer & Sohn Dachdeckerei GmbH",
        street="Baaderstr. 9",
        postal_code="80469",
        city="München",
        phone_raw="089/55508877",
        categories=["Dachdeckerei"],
        source_url="https://branchenbuch.example/muenchen/sailer-sohn",
    ),
    _listing(
        platform=Platform.DIRECTORY,
        platform_id="branchen/muenchen/alpenblick",
        name="Alpenblick Dach und Fassade KG",
        street="Rosenheimer Straße 45",
        postal_code="81669",
        city="München",
        phone_raw="089 5550 4410",
        email_raw="info@alpenblick-dach.example",
        categories=["Dachdeckerei", "Fassaden"],
        source_url="https://branchenbuch.example/muenchen/alpenblick",
    ),
    _listing(
        platform=Platform.DIRECTORY,
        platform_id="branchen/muenchen/vergleich24",
        name="Dachdecker Vergleich24 – Handwerkerportal",
        postal_code="80331",
        city="München",
        website="https://vergleich24.example",
        email_raw="service@vergleich24.example",
        categories=["Portal", "Vermittlung"],
        source_url="https://branchenbuch.example/muenchen/vergleich24",
    ),
]

ALL_LISTINGS: dict[Platform, list[Listing]] = {
    Platform.GOOGLE_MAPS: MAPS_LISTINGS,
    Platform.OPENSTREETMAP: OSM_LISTINGS,
    Platform.DIRECTORY: DIRECTORY_LISTINGS,
}

# --- Company websites ---------------------------------------------------
# Text as a fetcher would hand it over: tags stripped, layout gone, wording
# intact. The imprints follow the shape German law requires, which is why the
# extraction patterns can be as strict as they are.

PAGES: dict[str, list[WebPage]] = {
    "reiter-bedachungen.example": [
        WebPage(
            url="https://reiter-bedachungen.example/impressum",
            kind="impressum",
            text=(
                "Impressum\n"
                "Reiter Bedachungen GmbH\n"
                "Lindwurmstraße 112, 80337 München\n"
                "Vertreten durch: Martin Reiter\n"
                "Geschäftsführer: Martin Reiter\n"
                "Telefon: 089 5550 1234\n"
                "Fax: 089 5550 1235\n"
                "E-Mail: info@reiter-bedachungen.example\n"
                "Registergericht: Amtsgericht München, HRB 000000 (Beispiel)\n"
                "Umsetzung der Website: Studio Nordlicht, kontakt@studio-nordlicht.example\n"
            ),
        ),
        WebPage(
            url="https://reiter-bedachungen.example/team",
            kind="team",
            text=(
                "Ihr Team\n"
                "Martin Reiter, Geschäftsführer\n"
                "m.reiter@reiter-bedachungen.example\n"
                "Mobil: 0170 5550199\n"
                "Sabine Kluge, Ansprechpartnerin Auftragsannahme\n"
                "s.kluge@reiter-bedachungen.example\n"
                "Wir decken Steildächer, Flachdächer und Gauben im gesamten "
                "Münchner Süden. Notdienst nach Sturmschäden innerhalb von 24 Stunden.\n"
            ),
        ),
    ],
    "sailer-dach.example": [
        WebPage(
            url="https://sailer-dach.example/impressum",
            kind="impressum",
            text=(
                "Impressum\n"
                "Dachdeckerei Sailer & Sohn\n"
                "Baaderstraße 9, 80469 München\n"
                "Inhaber: Stefan Sailer\n"
                "Telefon: 089 5550 8877\n"
                "Anfragen bitte ausschließlich über das Kontaktformular. "
                "Eine E-Mail-Adresse veröffentlichen wir aus Gründen des "
                "Spamschutzes nicht.\n"
            ),
        )
    ],
    "bauzentrum-isartal.example": [
        WebPage(
            url="https://bauzentrum-isartal.example/impressum",
            kind="impressum",
            text=(
                "Impressum\n"
                "Bauzentrum Isartal e.K.\n"
                "Isartalstraße 30, 80469 München\n"
                "Vertreten durch: die Geschäftsleitung\n"
                "Telefon: 089 5550 2201\n"
                "E-Mail: info@bauzentrum-isartal.example\n"
            ),
        )
    ],
    "nordwind-dachtechnik.example": [
        WebPage(
            url="https://nordwind-dachtechnik.example/kontakt",
            kind="kontakt",
            text=(
                "Kontakt\n"
                "Nordwind Dachtechnik GmbH\n"
                "Schleißheimer Str. 210, 80797 München\n"
                "Geschäftsführerin: Ines Brandl\n"
                "Telefon: 089 5550 6600\n"
                "E-Mail: info@nordwind-dachtechnik.example\n"
                "Direkt: i.brandl@nordwind-dachtechnik.example\n"
                "Automatische Eingangsbestätigungen versendet "
                "noreply@nordwind-dachtechnik.example — dieses Postfach wird "
                "nicht gelesen.\n"
            ),
        )
    ],
}
