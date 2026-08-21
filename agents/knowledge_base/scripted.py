"""Scripted model answers for the knowledge base demo and tests.

Quotes here are copied verbatim from the fixture documents, because the
citation check compares them against the chunk text — a fixture that
paraphrased would fail its own verification, which is the behaviour under test.

`key_account_response` deliberately gets one citation wrong. The model answers
correctly from the support document and then attributes half of it to a chunk
that says nothing of the kind, which is precisely what a real model does when
an answer spans two documents and it loses track of which said what.
"""

from __future__ import annotations

from agents.knowledge_base.models import Citation, DraftAnswer
from core.llm import MockProvider, text_response

ANSWERS: dict[str, DraftAnswer] = {
    "restocking_fee": DraftAnswer(
        answer=(
            "Opened stock returned within 14 days is subject to a 15 percent "
            "restocking fee. Unopened stock returned within 30 days is refunded "
            "in full, with no fee."
        ),
        citations=[
            Citation(
                text="Opened stock returned within 14 days is subject to a 15 percent fee.",
                chunk_id="doc-returns#0",
                quote=(
                    "Opened stock may be returned within 14 days, subject to a 15 "
                    "percent restocking fee."
                ),
            ),
            Citation(
                text="Unopened stock within 30 days is refunded in full.",
                chunk_id="doc-returns#0",
                quote=(
                    "Customers may return unopened stock within 30 days of delivery "
                    "for a full refund."
                ),
            ),
        ],
    ),
    "warranty_scope": DraftAnswer(
        answer=(
            "Standard hardware carries a 24-month warranty from delivery, covering "
            "manufacturing defects and component failure under normal use. It "
            "excludes physical damage, liquid ingress, and wear to consumable "
            "parts such as keycaps and cables."
        ),
        citations=[
            Citation(
                text="The warranty runs 24 months from delivery.",
                chunk_id="doc-returns#0",
                quote=("Standard hardware carries a 24-month warranty from the date of delivery."),
            ),
            Citation(
                text="It excludes physical damage, liquid ingress and consumable wear.",
                chunk_id="doc-returns#0",
                quote=(
                    "It does not cover physical damage, liquid ingress, or wear to "
                    "consumable parts such as keycaps and cables."
                ),
            ),
        ],
        unanswered=[
            "Whether a bulk supply agreement overrides these terms for a specific "
            "customer — the policy says it can, but not what any given agreement says."
        ],
    ),
    "key_account_response": DraftAnswer(
        answer=(
            "Key accounts receive a four-hour first response during business "
            "hours, which run Monday to Friday, 09:00 to 17:00 CET. Warranty "
            "claims are covered by standard support and handled on the same "
            "priority terms for key accounts."
        ),
        citations=[
            Citation(
                text="Key accounts get a four-hour first response in business hours.",
                chunk_id="doc-support#0",
                quote=(
                    "Key accounts receive priority support with a four-hour first "
                    "response during business hours"
                ),
            ),
            # Correct fact, wrong document: the claim is in doc-support, not
            # doc-returns. The verifier catches the attribution, not the fact.
            Citation(
                text="Warranty claims fall under standard support.",
                chunk_id="doc-returns#0",
                quote="Standard support covers configuration questions, warranty claims",
            ),
        ],
    ),
}


def provider_for(question_key: str, *, model: str = "claude-opus-5") -> MockProvider:
    """Build a scripted provider for one demo question.

    There is no entry for `parental_leave` on purpose: the retriever refuses
    that question before the model is consulted, so a scripted answer for it
    would never be used. If the gate ever stopped refusing, the mock would run
    out of responses and the test would fail loudly — which is the right way to
    find out.
    """
    if question_key not in ANSWERS:
        raise KeyError(f"No scripted answer for {question_key!r}")
    return MockProvider([text_response(ANSWERS[question_key].model_dump_json())], model=model)
