"""Tests for merging listings into one row per business.

Two failure modes matter here and they are not symmetrical. Failing to merge
leaves a visible duplicate somebody fixes in a second. Merging two different
businesses loses one of them silently, and nobody ever finds out. The tests are
weighted accordingly.
"""

from __future__ import annotations

from agents.prospecting.merge import (
    build_leads,
    confidence_for,
    group_listings,
    normalise_name,
)
from agents.prospecting.models import ContactStatus, Listing, Platform, WebPage


def listing(**overrides) -> Listing:
    base = {
        "platform": Platform.GOOGLE_MAPS,
        "platform_id": "p1",
        "name": "Reiter Bedachungen GmbH",
        "street": "Lindwurmstraße 112",
        "postal_code": "80337",
        "city": "München",
    }
    return Listing(**{**base, **overrides})


# --- Names --------------------------------------------------------------


def test_the_legal_form_is_not_part_of_the_identity():
    assert normalise_name("Alpenblick Dach und Fassade KG") == normalise_name(
        "Alpenblick Dach & Fassade"
    )


def test_case_and_accents_do_not_split_a_business():
    assert normalise_name("Müller & Söhne GmbH") == normalise_name("MUELLER UND SOEHNE")


# --- Grouping -----------------------------------------------------------


def test_the_same_name_at_the_same_postcode_is_one_business():
    groups = group_listings(
        [
            listing(),
            listing(platform=Platform.OPENSTREETMAP, platform_id="o1", name="Reiter Bedachungen"),
        ]
    )

    assert len(groups) == 1


def test_a_shared_phone_number_merges_two_spellings():
    groups = group_listings(
        [
            listing(
                name="Alpenblick Dach & Fassade", postal_code="81669", phone_raw="089 5550 4410"
            ),
            listing(
                platform=Platform.DIRECTORY,
                platform_id="d1",
                name="Alpenblick Dach und Fassade KG",
                postal_code="81669",
                phone_raw="+49 89 55504410",
            ),
        ]
    )

    assert len(groups) == 1


def test_matching_is_transitive():
    """A matches B on a phone number, B matches C on a domain: all three merge."""
    groups = group_listings(
        [
            listing(name="Alpha", postal_code="80337", phone_raw="089 5550 1111"),
            listing(
                platform=Platform.OPENSTREETMAP,
                platform_id="o1",
                name="Beta",
                postal_code="80999",
                phone_raw="089 5550 1111",
                website="https://one.example",
            ),
            listing(
                platform=Platform.DIRECTORY,
                platform_id="d1",
                name="Gamma",
                postal_code="80998",
                website="https://one.example",
            ),
        ]
    )

    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_the_same_name_in_a_different_town_stays_two_businesses():
    groups = group_listings(
        [
            listing(postal_code="80337"),
            listing(platform=Platform.DIRECTORY, platform_id="d1", postal_code="81669"),
        ]
    )

    assert len(groups) == 2


def test_grouping_is_stable_across_runs():
    listings = [
        listing(name="Zeta", postal_code="80337"),
        listing(platform=Platform.DIRECTORY, platform_id="d1", name="Alpha", postal_code="81669"),
    ]

    first = [[entry.name for entry in group] for group in group_listings(listings)]
    second = [[entry.name for entry in group] for group in group_listings(listings)]

    assert first == second == [["Zeta"], ["Alpha"]]


# --- Merged records -----------------------------------------------------


def test_a_confirmed_address_beats_the_same_one_from_a_directory():
    leads, _ = build_leads(
        [
            listing(website="https://reiter.example", email_raw="info@reiter.example"),
            listing(
                platform=Platform.DIRECTORY,
                platform_id="d1",
                website="https://reiter.example",
                email_raw="info@reiter.example",
            ),
        ],
        {
            "reiter.example": [
                WebPage(
                    url="https://reiter.example/impressum",
                    kind="impressum",
                    text="E-Mail: info@reiter.example",
                )
            ]
        },
    )
    addresses = [contact for contact in leads[0].emails if contact.value == "info@reiter.example"]

    assert len(addresses) == 1
    assert addresses[0].status is ContactStatus.CONFIRMED
    assert "also on" in addresses[0].note


def test_duplicates_are_counted():
    _, duplicates = build_leads(
        [
            listing(),
            listing(platform=Platform.OPENSTREETMAP, platform_id="o1", name="Reiter Bedachungen"),
        ]
    )

    assert duplicates == 1


def test_more_platforms_means_more_confidence():
    one = confidence_for([listing()], [])
    two = confidence_for(
        [listing(), listing(platform=Platform.OPENSTREETMAP, platform_id="o1")], []
    )

    assert two > one


def test_lead_ids_are_stable_for_the_same_input():
    listings = [listing()]
    first, _ = build_leads(listings)
    second, _ = build_leads(listings)

    assert first[0].id == second[0].id
