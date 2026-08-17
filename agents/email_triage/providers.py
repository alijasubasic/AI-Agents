"""External services behind interfaces.

Two services are needed: the mailbox itself, and a CRM to look up who is
writing. Each has a `Protocol`, a mock backed by synthetic fixtures, and a real
implementation. Mock is the default everywhere — see
docs/adr/0002-mock-providers-by-default.md.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from agents.email_triage.fixtures import INBOX
from agents.email_triage.models import Email


class SentReply(BaseModel):
    """A reply the agent handed to the mailbox."""

    email_id: str
    body: str


# --- Mailbox ------------------------------------------------------------


class MailboxProvider(Protocol):
    """The mailbox operations this agent needs."""

    def fetch_unread(self, limit: int = 50) -> list[Email]: ...

    def send_reply(self, email_id: str, body: str) -> None: ...

    def add_label(self, email_id: str, label: str) -> None: ...


class MockMailbox:
    """An in-memory mailbox over the synthetic fixtures.

    Sends and labels are recorded rather than performed, so tests can assert
    that the agent *would* have sent something without anything leaving the
    machine.
    """

    def __init__(self, emails: list[Email] | None = None) -> None:
        self._emails = list(emails if emails is not None else INBOX)
        self.sent: list[SentReply] = []
        self.labels: dict[str, list[str]] = {}

    def fetch_unread(self, limit: int = 50) -> list[Email]:
        return self._emails[:limit]

    def send_reply(self, email_id: str, body: str) -> None:
        self.sent.append(SentReply(email_id=email_id, body=body))

    def add_label(self, email_id: str, label: str) -> None:
        self.labels.setdefault(email_id, []).append(label)


class GmailMailbox:
    """Gmail-backed mailbox.

    NOT COVERED BY TESTS. Nothing in CI exercises this class, because doing so
    would require a real Google account. It is written to the documented Gmail
    API shape and should be treated as unverified until someone runs it against
    a live mailbox. The mock is what the test suite and every eval use.

    Requires the optional `google` extra and OAuth credentials.
    """

    def __init__(self, credentials_path: str, user_id: str = "me") -> None:
        try:
            from google.oauth2.credentials import Credentials  # type: ignore[import-not-found]
            from googleapiclient.discovery import build  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "GmailMailbox needs the optional Google client libraries: uv sync --extra google"
            ) from exc

        self._service = build(
            "gmail", "v1", credentials=Credentials.from_authorized_user_file(credentials_path)
        )
        self._user_id = user_id

    def fetch_unread(self, limit: int = 50) -> list[Email]:  # pragma: no cover
        raise NotImplementedError(
            "Live Gmail fetching is not implemented yet. The message-to-Email "
            "mapping needs to handle multipart bodies, and that deserves "
            "contract tests against a real mailbox before it is trusted."
        )

    def send_reply(self, email_id: str, body: str) -> None:  # pragma: no cover
        raise NotImplementedError("Live Gmail sending is not implemented yet.")

    def add_label(self, email_id: str, label: str) -> None:  # pragma: no cover
        raise NotImplementedError("Live Gmail labelling is not implemented yet.")


# --- CRM ----------------------------------------------------------------


class Account(BaseModel):
    """What the agent is allowed to know about a sender."""

    domain: str
    company: str
    tier: str
    open_orders: list[str] = []
    lifetime_value_eur: int = 0
    notes: str = ""


class CrmProvider(Protocol):
    def lookup_account(self, domain: str) -> Account | None: ...


#: Synthetic accounts matching the fixture inbox. Invented, like everything else.
_ACCOUNTS: dict[str, Account] = {
    "nordwind-logistik.example": Account(
        domain="nordwind-logistik.example",
        company="Nordwind Logistik GmbH",
        tier="standard",
        open_orders=["A-1043"],
        lifetime_value_eur=48_000,
        notes="Reliable payer. Orders quarterly.",
    ),
    "alpina-ag.example": Account(
        domain="alpina-ag.example",
        company="Alpina AG",
        tier="key_account",
        open_orders=["A-1044"],
        lifetime_value_eur=310_000,
        notes="Order A-1044 delayed twice. Escalated internally on 2026-02-27.",
    ),
    "sudwest-handel.example": Account(
        domain="sudwest-handel.example",
        company="Südwest Handel KG",
        tier="standard",
        open_orders=[],
        lifetime_value_eur=92_000,
        notes="Billing contact changed in January.",
    ),
    "kestrel-systems.example": Account(
        domain="kestrel-systems.example",
        company="Kestrel Systems",
        tier="standard",
        open_orders=[],
        lifetime_value_eur=15_000,
        notes="",
    ),
}


class MockCrm:
    """Fixture-backed CRM lookups."""

    def __init__(self, accounts: dict[str, Account] | None = None) -> None:
        self._accounts = dict(accounts if accounts is not None else _ACCOUNTS)
        #: Every domain the agent asked about, so tests can assert on tool use.
        self.queries: list[str] = []

    def lookup_account(self, domain: str) -> Account | None:
        self.queries.append(domain)
        return self._accounts.get(domain.lower().strip())


class HttpCrm:
    """CRM over a REST API.

    NOT COVERED BY TESTS, for the same reason as :class:`GmailMailbox`: there is
    no CRM to test against. The shape is here so the seam is real; the mock is
    what everything in CI uses.
    """

    def __init__(self, base_url: str, token: str, timeout_s: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s

    def lookup_account(self, domain: str) -> Account | None:  # pragma: no cover
        raise NotImplementedError(
            "Live CRM lookup is not implemented. Add an HTTP client, map the "
            "response onto Account, and write contract tests before using it."
        )

    def _headers(self) -> dict[str, Any]:  # pragma: no cover
        return {"Authorization": f"Bearer {self._token}"}
