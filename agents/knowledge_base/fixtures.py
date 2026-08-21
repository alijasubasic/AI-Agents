"""A synthetic customer-document corpus.

Invented company, invented policies. Four documents chosen so the sufficiency
gate has something to do: two that answer questions well, one that answers a
question *partly*, and a question in the demo that the corpus cannot answer at
all.
"""

from __future__ import annotations

from agents.knowledge_base.models import Document

CORPUS: list[Document] = [
    Document(
        id="doc-returns",
        title="Returns and warranty policy",
        source="handbook/returns.md",
        text=(
            "Returns and warranty policy\n\n"
            "Standard hardware carries a 24-month warranty from the date of "
            "delivery. The warranty covers manufacturing defects and component "
            "failure under normal use. It does not cover physical damage, "
            "liquid ingress, or wear to consumable parts such as keycaps and "
            "cables.\n\n"
            "Customers may return unopened stock within 30 days of delivery for "
            "a full refund. Opened stock may be returned within 14 days, "
            "subject to a 15 percent restocking fee. Custom-configured units "
            "are not returnable once assembly has begun.\n\n"
            "Warranty claims require the original order reference. Replacement "
            "units ship within five working days of the returned unit arriving "
            "at our warehouse. Where a replacement is unavailable, we issue a "
            "credit note at the original purchase price.\n\n"
            "Bulk orders above 100 units are handled under the terms of the "
            "individual supply agreement, which takes precedence over this "
            "policy where the two differ."
        ),
    ),
    Document(
        id="doc-lead-times",
        title="Lead times and shipping",
        source="handbook/lead-times.md",
        text=(
            "Lead times and shipping\n\n"
            "Stocked items ship within two working days of order confirmation. "
            "The KB-88 keyboard and MS-12 mouse are held in stock year round.\n\n"
            "Configure-to-order units have a lead time of three to four weeks "
            "depending on component availability. Lead times are confirmed at "
            "the point of order and not before; quoting a date from this "
            "document without checking current capacity is a common source of "
            "complaints.\n\n"
            "Shipping within the EU is by road freight and typically takes two "
            "to four working days after dispatch. Shipments to North America go "
            "by air and clear customs in three to five working days. We do not "
            "ship to addresses outside the EU and North America.\n\n"
            "Expedited shipping is available on stocked items only and must be "
            "agreed with sales before the order is placed."
        ),
    ),
    Document(
        id="doc-support",
        title="Support tiers and response times",
        source="handbook/support.md",
        text=(
            "Support tiers and response times\n\n"
            "Standard support is available Monday to Friday, 09:00 to 17:00 "
            "CET. First response is within one working day. Standard support "
            "covers configuration questions, warranty claims, and order status "
            "enquiries.\n\n"
            "Key accounts receive priority support with a four-hour first "
            "response during business hours and a named account contact. "
            "Priority support does not include out-of-hours cover; there is no "
            "24/7 tier.\n\n"
            "Escalation to engineering happens when a fault affects more than "
            "one unit from the same batch, or when a customer's production is "
            "stopped. Engineering escalations are reviewed daily at 10:00 CET."
        ),
    ),
    Document(
        id="doc-onboarding",
        title="New customer onboarding",
        source="handbook/onboarding.md",
        text=(
            "New customer onboarding\n\n"
            "New accounts are set up within two working days of a signed supply "
            "agreement. Setup includes a credit check, which is run by finance "
            "and takes a further one to three days for accounts requesting "
            "payment terms.\n\n"
            "Default payment terms are 30 days net. Extended terms of 60 days "
            "are available to accounts with twelve months of trading history "
            "and are approved by finance case by case.\n\n"
            "Each new account is offered a 45-minute onboarding call covering "
            "ordering, support routes, and warranty handling."
        ),
    ),
]


#: Questions the demo asks, chosen to exercise every sufficiency verdict.
#: Named for what they ask rather than for the verdict they produce — the
#: verdict is the retriever's job to decide, and naming a fixture after the
#: answer is how a fixture starts lying when the code changes.
QUESTIONS: dict[str, str] = {
    "restocking_fee": "What restocking fee applies to opened stock?",
    "warranty_scope": "How long is the warranty on standard hardware, and what does it exclude?",
    "key_account_response": (
        "How quickly does a key account get a first response to a warranty claim?"
    ),
    "parental_leave": "What is the company's parental leave entitlement?",
}
