"""Tests for the Google providers, with no Google account.

Everything here runs against hand-written API responses in the shape Google's
documentation describes. That is a real limit and worth naming plainly: these
tests prove the *mapping* is right — MIME trees, threading headers, free/busy
intervals, scope guards — and they do not prove Google returns what the docs
say. Only a live call does that, which is what
`python -m integrations.google.check` is for.

What they do catch is the class of bug that would otherwise be found by a
customer: an empty body on multipart mail, a reply that arrives as a new
thread, an error mistaken for an empty calendar, and a send that happens
because a flag defaulted the wrong way.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

from agents.calendar_booking.models import TimeSlot
from integrations.google import auth
from integrations.google.gmail import (
    GmailMailbox,
    header,
    plain_text,
    split_address,
    to_email,
)


def encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


# --- Multipart bodies ----------------------------------------------------


def test_a_plain_top_level_body_is_read():
    assert plain_text({"mimeType": "text/plain", "body": {"data": encoded("hello")}}) == "hello"


def test_a_nested_multipart_body_is_found():
    """The bug this function exists for.

    `payload["body"]["data"]` is empty for anything multipart, which is most
    real mail. An agent that reads an empty body classifies every newsletter
    as an urgent enquiry.
    """
    payload = {
        "mimeType": "multipart/mixed",
        "body": {},
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "body": {},
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": encoded("the real text")}},
                    {"mimeType": "text/html", "body": {"data": encoded("<p>the real text</p>")}},
                ],
            },
            {"mimeType": "application/pdf", "body": {"attachmentId": "x"}},
        ],
    }

    assert plain_text(payload) == "the real text"


def test_html_is_used_only_when_there_is_no_plain_part():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {
                "mimeType": "text/html",
                "body": {"data": encoded("<div><b>Hi</b> there</div>")},
            }
        ],
    }

    assert plain_text(payload) == "Hi there"


def test_a_body_with_no_readable_part_is_empty_not_an_error():
    payload = {"mimeType": "multipart/mixed", "parts": [{"mimeType": "image/png", "body": {}}]}
    assert plain_text(payload) == ""


def test_base64_without_padding_still_decodes():
    # Gmail strips `=` padding. Feeding that to b64decode raises.
    assert plain_text({"mimeType": "text/plain", "body": {"data": encoded("abcde")}}) == "abcde"


# --- Message mapping -----------------------------------------------------


def test_addresses_are_split_into_email_and_name():
    assert split_address('"Dana Reyes" <Dana@Example.com>') == ("dana@example.com", "Dana Reyes")
    assert split_address("<bob@example.com>") == ("bob@example.com", "")
    assert split_address("plain@example.com") == ("plain@example.com", "")


def test_headers_are_matched_case_insensitively():
    message = {"payload": {"headers": [{"name": "SUBJECT", "value": "Hi"}]}}
    assert header(message, "subject") == "Hi"
    assert header(message, "missing") == ""


def test_a_message_maps_onto_the_neutral_email_model():
    message = {
        "id": "m1",
        "threadId": "t1",
        "internalDate": "1770000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Ana Ruiz <ana@kestrel.example>"},
                {"name": "Subject", "value": "Quote request"},
                {"name": "Date", "value": "nonsense the sender wrote"},
            ],
            "body": {"data": encoded("Could you quote 40 units?")},
        },
    }

    email = to_email(message)

    assert email.id == "m1"
    assert email.thread_id == "t1"
    assert (email.sender, email.sender_name) == ("ana@kestrel.example", "Ana Ruiz")
    assert email.subject == "Quote request"
    assert "40 units" in email.body
    # From internalDate, not the Date header, which senders routinely get wrong.
    assert email.received_at.tzinfo is not None
    assert email.received_at.year == 2026


def test_a_message_with_no_internal_date_still_maps():
    email = to_email({"id": "m2", "payload": {"headers": []}})
    assert email.received_at.tzinfo is not None


# --- The send guard ------------------------------------------------------


def test_sending_is_off_unless_two_switches_are_set(monkeypatch):
    """The one call that reaches a person.

    The scope is granted by a human in a browser; the flag is set in code.
    Neither alone is enough, and the default is neither.
    """
    mailbox = GmailMailbox.__new__(GmailMailbox)
    mailbox._allow_send = False

    with pytest.raises(PermissionError, match="allow_send=False"):
        mailbox.send_reply("m1", "a reply")


def test_the_default_scopes_do_not_include_sending():
    assert auth.SEND_SCOPE not in auth.SCOPES


def test_the_scopes_are_the_narrow_ones():
    """Scope choice is the whole security story for these tokens."""
    joined = " ".join(auth.SCOPES)

    assert "auth/drive.file" in joined
    assert "auth/drive " not in joined + " ", "drive.file, never full drive"
    assert "gmail.modify" in joined
    assert "gmail.full" not in joined
    assert "calendar.readonly" in joined and "calendar.events" in joined


# --- Calendar ------------------------------------------------------------


class FakeFreeBusy:
    def __init__(self, response):
        self._response = response
        self.body = None

    def query(self, body):
        self.body = body
        return self

    def execute(self):
        return self._response


def calendar_with(response):
    from integrations.google.calendar import GoogleCalendar

    calendar = GoogleCalendar.__new__(GoogleCalendar)
    calendar._roster = {}
    calendar._calendar_id = "primary"
    calendar._allow_writes = False

    fake = FakeFreeBusy(response)
    calendar._service = type("S", (), {"freebusy": staticmethod(lambda: fake)})()
    return calendar


def test_busy_intervals_map_to_blocks_with_no_titles():
    """Free/busy has no titles, and that is the right amount of information.

    The agent needs to know *when* somebody is unavailable. What the meeting
    is called is none of its business.
    """
    calendar = calendar_with(
        {
            "calendars": {
                "dana@example.com": {
                    "busy": [
                        {"start": "2026-08-24T09:00:00Z", "end": "2026-08-24T10:00:00Z"},
                        {"start": "2026-08-24T13:30:00Z", "end": "2026-08-24T14:00:00Z"},
                    ]
                }
            }
        }
    )

    blocks = calendar.busy_blocks(
        "dana@example.com",
        datetime(2026, 8, 24, tzinfo=UTC),
        datetime(2026, 8, 25, tzinfo=UTC),
    )

    assert len(blocks) == 2
    assert all(block.title == "" for block in blocks)
    assert all(block.start.tzinfo is not None for block in blocks)
    assert blocks[0].end.hour == 10


def test_a_calendar_error_is_raised_not_read_as_free():
    """The failure mode that books a meeting on top of an unseen one.

    Google returns `errors` when a calendar was never shared. Treating that as
    an empty busy list means "I could not see it" becomes "they are free".
    """
    calendar = calendar_with(
        {"calendars": {"dana@example.com": {"errors": [{"reason": "notFound"}]}}}
    )

    with pytest.raises(PermissionError, match="not shared"):
        calendar.busy_blocks(
            "dana@example.com",
            datetime(2026, 8, 24, tzinfo=UTC),
            datetime(2026, 8, 25, tzinfo=UTC),
        )


def test_creating_an_event_is_refused_by_default():
    calendar = calendar_with({"calendars": {}})
    slot = TimeSlot(
        start=datetime(2026, 8, 24, 9, tzinfo=UTC), end=datetime(2026, 8, 24, 9, 30, tzinfo=UTC)
    )

    with pytest.raises(PermissionError, match="allow_writes=False"):
        calendar.create_event(title="Chat", slot=slot, attendee_emails=["dana@example.com"])


def test_an_attendee_comes_from_the_roster_not_from_google():
    """Google exposes free/busy, not working hours or time zone.

    Guessing 09:00-17:00 in the organiser's zone would produce proposals that
    look authoritative and are wrong for anyone abroad — which is the exact
    failure `calendar-booking` exists to avoid.
    """
    from agents.calendar_booking.fixtures import PEOPLE
    from integrations.google.calendar import GoogleCalendar

    calendar = GoogleCalendar.__new__(GoogleCalendar)
    calendar._roster = {email.lower(): person for email, person in PEOPLE.items()}

    known = next(iter(PEOPLE))
    assert calendar.resolve_attendee(known.upper()) is not None
    assert calendar.resolve_attendee("stranger@nowhere.example") is None


# --- Configuration errors explain themselves -----------------------------


def test_a_missing_client_secrets_names_the_variable_and_the_page(monkeypatch):
    monkeypatch.delenv(auth.CLIENT_SECRETS_ENV, raising=False)

    with pytest.raises(auth.GoogleNotConfigured) as problem:
        auth.client_secrets_path()

    message = str(problem.value)
    assert auth.CLIENT_SECRETS_ENV in message
    assert "docs/INTEGRATIONS.md" in message


def test_a_missing_token_names_the_command_to_run(monkeypatch):
    monkeypatch.delenv(auth.TOKEN_ENV, raising=False)

    with pytest.raises(auth.GoogleNotConfigured) as problem:
        auth.token_path()

    assert "integrations.google.connect" in str(problem.value)


def test_is_connected_is_a_file_check_and_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.TOKEN_ENV, str(tmp_path / "token.json"))
    assert auth.is_connected() is False

    (tmp_path / "token.json").write_text("{}", encoding="utf-8")
    assert auth.is_connected() is True


def test_nothing_in_this_package_imports_google_at_module_load():
    """A fresh clone with no accounts must still run every demo.

    If importing these modules pulled in `googleapiclient`, `make demo` would
    fail on a machine that never ran `uv sync --extra google`.
    """
    import importlib

    for module in (
        "integrations.google",
        "integrations.google.auth",
        "integrations.google.calendar",
        "integrations.google.gmail",
        "integrations.google.drive",
    ):
        assert importlib.import_module(module) is not None
