"""Tests for contact extraction.

This module decides what ends up in somebody's mailbox, so it gets the densest
coverage in the package. Every test here is a case that produced a wrong lead
row at some point while the module was being written.
"""

from __future__ import annotations

import pytest

from agents.prospecting.extraction import (
    attribute_email,
    construct_email,
    contacts_from_listing,
    contacts_from_page,
    deobfuscate,
    extract_emails,
    extract_people,
    extract_phones,
    is_undeliverable,
    normalise_email,
    normalise_phone,
    people_from_pages,
)
from agents.prospecting.models import ContactStatus, Listing, Person, Platform, WebPage

# --- Phone numbers ------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("089 5550 1234", "+498955501234"),
        ("089/5550-1234", "+498955501234"),
        ("(089) 5550 1234", "+498955501234"),
        ("+49 89 55501234", "+498955501234"),
        ("0049 89 55501234", "+498955501234"),
        ("+49 (0) 89 55501234", "+498955501234"),
        ("0170 5550199", "+491705550199"),
    ],
)
def test_german_numbers_normalise_to_one_form(written: str, expected: str):
    assert normalise_phone(written) == expected


@pytest.mark.parametrize(
    "written",
    [
        "5550 123",  # no country prefix and no national zero
        "80337",  # a postal code
        "089 12",  # too short to be a number
        "",
    ],
)
def test_an_ambiguous_number_is_refused_rather_than_guessed(written: str):
    assert normalise_phone(written) is None


def test_a_fax_line_is_not_collected_as_a_phone_number():
    text = "Telefon: 089 5550 1234\nFax: 089 5550 1235\n"
    numbers = dict(extract_phones(text))

    assert "+498955501234" in numbers
    assert "+498955501235" not in numbers


def test_a_mobile_number_keeps_its_label():
    assert extract_phones("Mobil: 0170 5550199") == [("+491705550199", "Mobil")]


# --- Email addresses ----------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("info (at) reiter.example", "info@reiter.example"),
        ("info [at] reiter [dot] example", "info@reiter.example"),
        ("info at reiter punkt example", "info@reiter.example"),
        ("INFO@Reiter.Example", "info@reiter.example"),
    ],
)
def test_obfuscated_addresses_are_recovered(written: str, expected: str):
    assert normalise_email(written) == expected


def test_something_that_is_not_an_address_is_not_one():
    assert normalise_email("Impressum") is None
    assert normalise_email("info@") is None


def test_a_no_reply_address_is_recognised():
    assert is_undeliverable("noreply@nordwind.example")
    assert is_undeliverable("do-not-reply@nordwind.example")
    assert not is_undeliverable("info@nordwind.example")


def test_deobfuscation_leaves_ordinary_text_alone():
    assert deobfuscate("Dachdecker in München") == "Dachdecker in München"


def test_addresses_are_returned_in_the_order_they_appear():
    text = "b@x.example und a@x.example und b@x.example"
    assert extract_emails(text) == ["b@x.example", "a@x.example"]


# --- People -------------------------------------------------------------


def test_a_role_before_the_name_is_found():
    people = extract_people("Geschäftsführer: Martin Reiter")

    assert [p.name for p in people] == ["Martin Reiter"]
    assert people[0].role == "Geschäftsführer"


def test_a_role_after_the_name_is_found():
    people = extract_people("Martin Reiter, Geschäftsführer")

    assert [p.name for p in people] == ["Martin Reiter"]


def test_a_name_does_not_run_into_the_next_line():
    """The regression that made "Stefan Sailer Telefon" a person.

    German imprints put the phone number on the line after the owner's name.
    Matching across the line break produced a person whose surname was
    "Telefon", and then an email address addressed to them.
    """
    people = extract_people("Inhaber: Stefan Sailer\nTelefon: 089 5550 8877\n")

    assert [p.name for p in people] == ["Stefan Sailer"]


def test_a_role_with_no_person_behind_it_produces_nobody():
    assert extract_people("Vertreten durch: die Geschäftsleitung") == []


def test_a_title_is_not_part_of_the_name():
    people = extract_people("Geschäftsführer: Dr. Martin Reiter")

    assert people[0].name == "Martin Reiter"


# --- Attribution --------------------------------------------------------


def person(name: str) -> Person:
    return Person(name=name, role="Geschäftsführer")


@pytest.mark.parametrize(
    "address",
    [
        "m.reiter@x.example",
        "mreiter@x.example",
        "reiter@x.example",
        "martin.reiter@x.example",
    ],
)
def test_a_personal_address_is_matched_to_its_person(address: str):
    matched = attribute_email(address, [person("Martin Reiter")])

    assert matched is not None
    assert matched.name == "Martin Reiter"


@pytest.mark.parametrize("address", ["info@x.example", "martin@x.example", "buero@x.example"])
def test_a_shared_mailbox_is_matched_to_nobody(address: str):
    """A first name alone is not enough: plenty of firms have two Michaels."""
    assert attribute_email(address, [person("Martin Reiter")]) is None


def test_an_accented_surname_still_matches():
    matched = attribute_email("s.mueller@x.example", [person("Sabine Müller")])

    assert matched is not None


# --- Status -------------------------------------------------------------


def page(text: str, *, url: str = "https://reiter.example/impressum") -> WebPage:
    return WebPage(url=url, kind="impressum", text=text)


def test_an_address_on_the_businesss_own_domain_is_confirmed():
    contacts = contacts_from_page(page("E-Mail: info@reiter.example"))

    assert contacts[0].status is ContactStatus.CONFIRMED


def test_the_web_agency_in_the_footer_is_not_the_business():
    """The classic false positive: whoever built the site leaves an address."""
    contacts = contacts_from_page(
        page("E-Mail: info@reiter.example\nUmsetzung: kontakt@studio.example")
    )
    by_value = {contact.value: contact for contact in contacts}

    assert by_value["info@reiter.example"].status is ContactStatus.CONFIRMED
    assert by_value["kontakt@studio.example"].status is ContactStatus.REPORTED
    assert "studio.example" in by_value["kontakt@studio.example"].note


def test_a_no_reply_address_on_the_page_is_invalid():
    contacts = contacts_from_page(page("Bestätigungen von noreply@reiter.example"))

    assert contacts[0].status is ContactStatus.INVALID


def test_a_directory_listing_is_only_ever_reported():
    listing = Listing(
        platform=Platform.DIRECTORY,
        platform_id="d1",
        name="Reiter",
        email_raw="info@reiter.example",
        phone_raw="089 5550 1234",
        source_url="https://branchenbuch.example/reiter",
    )
    statuses = {contact.kind: contact.status for contact in contacts_from_listing(listing)}

    assert statuses == {"email": ContactStatus.REPORTED, "phone": ContactStatus.REPORTED}


def test_a_constructed_address_is_labelled_as_a_guess():
    guess = construct_email(person("Stefan Sailer"), "sailer.example")

    assert guess is not None
    assert guess.value == "s.sailer@sailer.example"
    assert guess.status is ContactStatus.CONSTRUCTED
    assert not guess.contactable


def test_nothing_is_constructed_without_a_domain():
    assert construct_email(person("Stefan Sailer"), "") is None


def test_a_person_gets_the_address_that_names_them():
    people = people_from_pages(
        [
            page(
                "Geschäftsführer: Martin Reiter\n"
                "m.reiter@reiter.example\n"
                "Zentrale: info@reiter.example\n"
            )
        ]
    )

    assert len(people) == 1
    assert people[0].email == "m.reiter@reiter.example"
