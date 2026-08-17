"""Synthetic inbox fixtures.

Every message here is invented. No real customer, address, or business detail
appears in this repository — see docs/adr/0002-mock-providers-by-default.md.

The set is chosen to cover the cases that matter for triage: one that should be
answered automatically, several that must escalate for different reasons, and
one that is genuinely ambiguous.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agents.email_triage.models import Email


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """Fixed timestamps in March 2026 — fixtures must not drift with the clock."""
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


INBOX: list[Email] = [
    Email(
        id="msg-001",
        sender="p.hartmann@nordwind-logistik.example",
        sender_name="Petra Hartmann",
        subject="Question about bulk pricing for KB-88",
        body=(
            "Hello,\n\n"
            "We are planning to order around 200 units of the KB-88 keyboard in "
            "Q2 and wanted to ask whether you offer volume pricing at that "
            "quantity.\n\n"
            "Could you also confirm the current lead time? Our warehouse needs "
            "to plan intake capacity.\n\n"
            "Best regards,\nPetra Hartmann\nNordwind Logistik GmbH"
        ),
        received_at=_at(3, 9, 12),
        thread_id="t-001",
    ),
    Email(
        id="msg-002",
        sender="m.faber@alpina-ag.example",
        sender_name="Michael Faber",
        subject="RE: Order A-1044 — still not shipped, this is unacceptable",
        body=(
            "This is the third time I am writing about order A-1044.\n\n"
            "It was promised for February 20th. It is now March 4th. Nobody "
            "answers the phone, nobody replies to my emails. We have a "
            "production line standing still because of your delay.\n\n"
            "If this is not resolved by Friday I will be speaking to our lawyer "
            "about the contract, and I will make sure everyone in this industry "
            "hears about it.\n\n"
            "Michael Faber"
        ),
        received_at=_at(4, 8, 3),
        thread_id="t-002",
    ),
    Email(
        id="msg-003",
        sender="accounts@sudwest-handel.example",
        sender_name="Sabine Kruse",
        subject="Invoice 2026-0412 — duplicate charge?",
        body=(
            "Good morning,\n\n"
            "We received invoice 2026-0412 for EUR 4,180.00. Our records show we "
            "already paid invoice 2026-0397 for the same delivery on 12 February.\n\n"
            "Could you check whether this is a duplicate? If so we would need a "
            "refund or a credit note.\n\n"
            "Kind regards,\nSabine Kruse\nAccounts Payable"
        ),
        received_at=_at(4, 10, 45),
        thread_id="t-003",
    ),
    Email(
        id="msg-004",
        sender="t.berger@meridian-consulting.example",
        sender_name="Tobias Berger",
        subject="Intro call next week?",
        body=(
            "Hi,\n\n"
            "Following up on our conversation at the trade fair. Would you have "
            "30 minutes next week for a short intro call? Tuesday or Thursday "
            "afternoon would work well on my side.\n\n"
            "I am in CET.\n\n"
            "Best,\nTobias"
        ),
        received_at=_at(5, 14, 20),
        thread_id="t-004",
    ),
    Email(
        id="msg-005",
        sender="growth@leadrocket.example",
        sender_name="LeadRocket Growth Team",
        subject="🚀 Triple your B2B pipeline in 30 days (guaranteed)",
        body=(
            "Hey there,\n\n"
            "I noticed your company and thought you'd be a PERFECT fit for our "
            "AI-powered lead generation platform. We've helped 500+ companies "
            "triple their pipeline.\n\n"
            "Book a demo here: https://leadrocket.example/demo\n\n"
            "Unsubscribe | LeadRocket Inc."
        ),
        received_at=_at(5, 16, 55),
    ),
    Email(
        id="msg-006",
        sender="j.wolf@kestrel-systems.example",
        sender_name="Jana Wolf",
        subject="the thing we discussed",
        body=("Hi,\n\nCan you send it over when you get a chance?\n\nThanks\nJana"),
        received_at=_at(6, 11, 30),
        thread_id="t-006",
    ),
]


#: A short voice profile. Swapped per user; kept in code so the demo is
#: self-contained rather than depending on a config file.
VOICE_GUIDE = """\
Write like a competent, unhurried colleague:

- Plain English. No "I hope this email finds you well", no "reaching out".
- Answer the actual question in the first two sentences.
- Say what you do not know rather than hedging around it.
- Warm but not chummy. Contractions are fine; exclamation marks are not.
- Close with a concrete next step and who owns it.
- Never promise a date, price, or outcome that is not stated in the source
  material you were given.
"""


def by_id(email_id: str) -> Email:
    """Look up one fixture email, for tests and demo scenes."""
    for email in INBOX:
        if email.id == email_id:
            return email
    raise KeyError(f"No fixture email {email_id!r}")
