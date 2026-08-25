"""Gmail, behind the `MailboxProvider` interface.

Two parts of this are easy to get wrong and are worth reading before trusting
it against a real mailbox.

**Multipart bodies.** A Gmail message is a tree. `text/plain` may be nested
under `multipart/alternative` under `multipart/mixed`, and the naive
`payload["body"]["data"]` returns empty for most real mail. `plain_text` walks
the tree and prefers `text/plain`, falling back to stripping tags out of
`text/html` — because an agent that reads an empty body classifies every
newsletter as an urgent enquiry.

**Sending.** `send_reply` refuses unless the mailbox was constructed with
`allow_send=True` *and* the token carries `gmail.send`, which the default
scopes do not include. Two independent switches, because this is the one call
in the repository that reaches a customer. The architecture already puts every
reply through the supervisor and the codex first; this is the belt to that
pair of braces.
"""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from email.message import EmailMessage

from agents.email_triage.models import Email
from integrations.google.auth import GMAIL_SCOPES, SEND_SCOPE, service

_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def plain_text(payload: dict) -> str:
    """The readable body of a Gmail message payload.

    Walks the MIME tree rather than reading the top-level body, which is empty
    for anything multipart — which is to say, for most real mail.
    """
    plain, html = _collect(payload)
    if plain.strip():
        return plain.strip()
    if html.strip():
        return _WHITESPACE.sub(" ", _TAG.sub(" ", html)).strip()
    return ""


def _collect(part: dict) -> tuple[str, str]:
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data")

    if data and mime == "text/plain":
        return _decode(data), ""
    if data and mime == "text/html":
        return "", _decode(data)

    plain, html = "", ""
    for child in part.get("parts", []) or []:
        child_plain, child_html = _collect(child)
        plain += child_plain
        html += child_html
    return plain, html


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def header(message: dict, name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    for entry in headers:
        if entry.get("name", "").lower() == name.lower():
            return entry.get("value", "")
    return ""


def split_address(raw: str) -> tuple[str, str]:
    """`"Dana Reyes" <dana@x.com>` -> (dana@x.com, Dana Reyes)."""
    match = re.match(r"\s*(?:\"?(?P<name>[^\"<]*)\"?\s*)?<(?P<email>[^>]+)>\s*$", raw)
    if match:
        return match.group("email").strip().lower(), (match.group("name") or "").strip()
    return raw.strip().lower(), ""


def to_email(message: dict) -> Email:
    """One Gmail message as this repository's provider-neutral `Email`."""
    sender, sender_name = split_address(header(message, "From"))
    # `internalDate` is milliseconds since the epoch and is always present;
    # the `Date` header is written by the sender and is routinely wrong.
    stamp = message.get("internalDate")
    received = datetime.fromtimestamp(int(stamp) / 1000, tz=UTC) if stamp else datetime.now(tz=UTC)

    return Email(
        id=message["id"],
        sender=sender,
        sender_name=sender_name,
        subject=header(message, "Subject"),
        body=plain_text(message.get("payload", {})),
        received_at=received,
        thread_id=message.get("threadId"),
    )


class GmailMailbox:
    """Live mailbox access for one authenticated account."""

    def __init__(
        self,
        *,
        user_id: str = "me",
        query: str = "is:unread in:inbox",
        allow_send: bool = False,
    ) -> None:
        self._user_id = user_id
        self._query = query
        self._allow_send = allow_send
        scopes = GMAIL_SCOPES + ((SEND_SCOPE,) if allow_send else ())
        self._service = service("gmail", "v1", scopes=scopes)

    def fetch_unread(self, limit: int = 50) -> list[Email]:
        """Unread inbox mail, oldest first.

        Oldest first because a triage queue worked newest-first leaves the
        oldest enquiry rotting at the bottom forever.
        """
        listing = (
            self._service.users()
            .messages()
            .list(userId=self._user_id, q=self._query, maxResults=limit)
            .execute()
        )

        emails = []
        for stub in listing.get("messages", []):
            message = (
                self._service.users()
                .messages()
                .get(userId=self._user_id, id=stub["id"], format="full")
                .execute()
            )
            emails.append(to_email(message))
        return sorted(emails, key=lambda email: email.received_at)

    def add_label(self, email_id: str, label: str) -> None:
        """Apply a label, creating it the first time it is used."""
        self._service.users().messages().modify(
            userId=self._user_id,
            id=email_id,
            body={"addLabelIds": [self._label_id(label)]},
        ).execute()

    def _label_id(self, name: str) -> str:
        existing = self._service.users().labels().list(userId=self._user_id).execute()
        for label in existing.get("labels", []):
            if label.get("name") == name:
                return label["id"]
        created = (
            self._service.users()
            .labels()
            .create(
                userId=self._user_id,
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return created["id"]

    def send_reply(self, email_id: str, body: str) -> None:
        """Reply in-thread. The one call here that reaches a person.

        Two switches guard it, and they are independent on purpose: the scope
        is granted at consent time by a human in a browser, and the flag is set
        at construction time in code. Neither alone is enough.
        """
        if not self._allow_send:
            raise PermissionError(
                "GmailMailbox was built with allow_send=False, so it will not send. "
                "This is the default. See docs/INTEGRATIONS.md before changing it."
            )

        original = (
            self._service.users()
            .messages()
            .get(userId=self._user_id, id=email_id, format="metadata")
            .execute()
        )

        message = EmailMessage()
        message["To"] = header(original, "From")
        subject = header(original, "Subject")
        message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        # Threading headers, or the reply arrives as an unrelated new message.
        if message_id := header(original, "Message-ID"):
            message["In-Reply-To"] = message_id
            message["References"] = message_id
        message.set_content(body)

        self._service.users().messages().send(
            userId=self._user_id,
            body={
                "raw": base64.urlsafe_b64encode(message.as_bytes()).decode(),
                "threadId": original.get("threadId"),
            },
        ).execute()
