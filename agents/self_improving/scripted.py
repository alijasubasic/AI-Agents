"""Scripted behaviour for the improvement demo.

Three prompt versions, each with a fixed answer table. The tables are written
to show the loop's three outcomes on one run:

* **v1 accepted** — a real improvement: better on tuning *and* on holdout.
* **v2 rejected, no gain** — better on tuning, unchanged on holdout. This is
  the failure the split exists to catch: the prompt learned the examples it was
  shown. Without a holdout it would have looked like the best version yet.
* **v3 rejected, regression** — worse on holdout. Rolled back.

The answer tables are the mock's whole model of "how good is this prompt". A
live run replaces `scripted_runner` with one that actually calls the model and
changes nothing else.
"""

from __future__ import annotations

from agents.self_improving.models import (
    Critique,
    PromptProposal,
    PromptVersion,
    TaskCase,
)
from core.llm import MockProvider, text_response

#: What each version answers, per case id. Missing entries score zero.
#:
#: These tables are the mock's whole model of "how good is this prompt", and
#: they are shaped to put each version's failure in plain view:
#:
#:   v0   50% / 50%   underspecified baseline
#:   v1   75% / 75%   a real improvement: both splits move together
#:   v2  100% / 75%   perfect on what it saw, no better on what it did not
#:   v3  100% / 50%   an over-eager rewrite that breaks a category
ANSWERS: dict[int, dict[str, str]] = {
    # Baseline: names the departments and stops. Swaps money-already-spent
    # with money-about-to-be-spent, and treats a fault in delivered goods as
    # an order problem.
    0: {
        "t1": "billing",
        "t2": "technical",
        "t3": "billing",
        "t4": "sales",
        "t5": "sales",
        "t6": "sales",
        "t7": "other",
        "t8": "sales",
        "h1": "billing",
        "h2": "billing",
        "h3": "technical",
        "h4": "sales",
    },
    # v1: the billing/sales boundary is stated as a rule, so it generalises
    # to the holdout too. Still slips on two edge cases.
    1: {
        "t1": "billing",
        "t2": "technical",
        "t3": "sales",
        "t4": "billing",
        "t5": "sales",
        "t6": "technical",
        "t7": "sales",
        "t8": "sales",
        "h1": "sales",
        "h2": "billing",
        "h3": "technical",
        "h4": "sales",
    },
    # v2: the optimizer listed the specific tuning cases it was shown.
    # Perfect on those, unchanged on the holdout — it learned the examples,
    # not the task. This is the version the split exists to catch.
    2: {
        "t1": "billing",
        "t2": "technical",
        "t3": "sales",
        "t4": "billing",
        "t5": "sales",
        "t6": "technical",
        "t7": "other",
        "t8": "billing",
        "h1": "sales",
        "h2": "billing",
        "h3": "technical",
        "h4": "sales",
    },
    # v3: discouraging the catch-all category pulls unrelated messages into
    # sales. Holdout falls; rolled back.
    3: {
        "t1": "billing",
        "t2": "technical",
        "t3": "sales",
        "t4": "billing",
        "t5": "sales",
        "t6": "technical",
        "t7": "other",
        "t8": "billing",
        "h1": "sales",
        "h2": "billing",
        "h3": "sales",
        "h4": "sales",
    },
}


def scripted_runner(version: PromptVersion, cases: list[TaskCase]) -> dict[str, str]:
    """Answer a set of cases as the given version would."""
    table = ANSWERS.get(version.number, {})
    return {case.id: table.get(case.id, "") for case in cases}


CRITIQUES: list[Critique] = [
    Critique(
        patterns=[
            "Questions about money already spent are routed to sales, and "
            "questions about a prospective purchase to billing — the two are "
            "swapped",
            "A fault in goods already delivered is treated as an order problem "
            "rather than a technical one",
        ],
        suggestions=[
            "Say that billing covers money already owed or paid, and sales "
            "covers money not yet committed",
            "Say that anything not working is technical, whatever brought it "
            "into the customer's hands",
        ],
        verdict="Close: the categories are right, the boundary between two of them is not.",
    ),
    Critique(
        patterns=["Occasional slips on messages that mention more than one topic"],
        suggestions=["Say to route on what the customer wants done, not what they mention"],
        verdict="Nearly there; the remaining failures are ambiguous cases.",
    ),
    Critique(
        patterns=["A handful of messages fit no department cleanly"],
        suggestions=["Give more direction on when to choose a specific department"],
        verdict="Small gains left, if any.",
    ),
]

PROPOSALS: list[PromptProposal] = [
    PromptProposal(
        prompt=(
            "Route the customer message to a department.\n\n"
            "- billing: money already owed or paid — invoices, statements, "
            "credit notes, payment terms.\n"
            "- sales: money not yet committed — quotes, pricing for a "
            "prospective order, availability, distributors.\n"
            "- technical: anything not working as it should, whatever brought "
            "it into the customer's hands.\n"
            "- other: anything none of the above covers.\n\n"
            "Answer with exactly one of: billing, technical, sales, other.\n"
        ),
        rationale=(
            "States the billing/sales boundary as a rule about when money is "
            "committed, and makes faults technical regardless of origin."
        ),
    ),
    PromptProposal(
        prompt=(
            "Route the customer message to a department.\n\n"
            "- billing: money already owed or paid — invoices, statements, "
            "credit notes, payment terms, duplicate charges, missing credit "
            "notes, requests for past statements.\n"
            "- sales: quotes, pricing for a prospective order, availability, "
            "distributors, extending a rollout.\n"
            "- technical: anything not working — pairing failures, wrong parts "
            "shipped, overheating units, firmware.\n"
            "- other: mailing list requests.\n\n"
            "Answer with exactly one of: billing, technical, sales, other.\n"
        ),
        rationale=("Adds the specific situations seen in the failing examples to each category."),
    ),
    PromptProposal(
        prompt=(
            "Route the customer message to a department.\n\n"
            "Prefer a specific department over 'other' wherever the message "
            "touches on a product or a commercial relationship at all.\n\n"
            "- billing: money already owed or paid.\n"
            "- sales: money not yet committed, and any wider commercial "
            "question.\n"
            "- technical: anything not working.\n"
            "- other: use only when nothing else could possibly apply.\n\n"
            "Answer with exactly one of: billing, technical, sales, other.\n"
        ),
        rationale="Discourages the catch-all category so fewer messages land in it.",
    ),
]


def critic_provider(*, model: str = "claude-opus-5") -> MockProvider:
    """A critic scripted for the whole run."""
    return MockProvider(
        [text_response(critique.model_dump_json()) for critique in CRITIQUES],
        model=model,
    )


def optimizer_provider(*, model: str = "claude-opus-5") -> MockProvider:
    """An optimizer scripted for the whole run."""
    return MockProvider(
        [text_response(proposal.model_dump_json()) for proposal in PROPOSALS],
        model=model,
    )
