"""Sending, behind an interface.

One `Protocol`, a mock that records instead of sending, and a real SMTP
implementation. The mock is the default everywhere — see
docs/adr/0002-mock-providers-by-default.md — which is why the test suite can
assert that the system *would* have written to somebody without anything
leaving the machine.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol

from pydantic import BaseModel, Field


class OutboundMessage(BaseModel):
    """One email, ready to send."""

    to: str
    subject: str
    body: str
    from_name: str = ""
    from_email: str = ""
    reply_to: str = ""

    #: The address a recipient's mail client offers as a one-click unsubscribe.
    #: Gmail and Outlook both surface it; a cold email without one gets marked
    #: as spam instead, which costs the whole sending domain.
    unsubscribe_mailto: str = ""

    headers: dict[str, str] = Field(default_factory=dict)


class MailSender(Protocol):
    """The one operation outreach needs."""

    def send(self, message: OutboundMessage) -> str: ...


class MockSender:
    """Records what would have been sent. Sends nothing, ever."""

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    def send(self, message: OutboundMessage) -> str:
        self.sent.append(message)
        return f"mock-{len(self.sent):04d}"

    @property
    def recipients(self) -> list[str]:
        return [message.to for message in self.sent]


class SmtpSender:
    """Sends over SMTP with STARTTLS.

    NOT COVERED BY TESTS. Nothing in CI has a mail server to send to, and a test
    that mocked `smtplib` would only assert that this module calls the functions
    it visibly calls.

    Two headers are set that a hand-rolled sender usually forgets, and both are
    the difference between a campaign that reaches inboxes and one that trains
    every provider to file the sending domain under junk:
    `List-Unsubscribe` and `List-Unsubscribe=One-Click`.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str,
        password: str,
        use_tls: bool = True,
        timeout_s: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout_s = timeout_s

    def send(self, message: OutboundMessage) -> str:  # pragma: no cover - network
        mail = EmailMessage()
        mail["To"] = message.to
        mail["Subject"] = message.subject
        mail["From"] = formataddr((message.from_name or None, message.from_email or self._username))
        if message.reply_to:
            mail["Reply-To"] = message.reply_to

        if message.unsubscribe_mailto:
            mail["List-Unsubscribe"] = f"<mailto:{message.unsubscribe_mailto}?subject=Abmelden>"
            mail["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        for name, value in message.headers.items():
            mail[name] = value

        message_id = make_msgid()
        mail["Message-ID"] = message_id
        mail.set_content(message.body)

        with smtplib.SMTP(self._host, self._port, timeout=self._timeout_s) as server:
            if self._use_tls:
                server.starttls(context=ssl.create_default_context())
            server.login(self._username, self._password)
            server.send_message(mail)

        return message_id
