"""Scripted drafts and judgements for the brain demo and tests.

The drafts here are written to exercise the codex, and two of them are
deliberately bad in ways that a competent-sounding model produces every day:

* the Kestrel outreach repeats the revenue figure that `lead-research` labelled
  UNSOURCED, so a prospect would be told an invented number as fact
* the follow-up to call-003 is addressed to the email address `call-intake`
  established the caller never actually said
* the Halvard outreach guarantees a discount and manufactures a deadline

None of the agents that produced these notice anything wrong. That is the
point: the codex is the thing that notices.
"""

from __future__ import annotations

from agents.brain.codex import apply_codex, codex_verdict
from agents.brain.models import Decision, Judgement, Verdict
from core.llm import MockProvider, text_response

#: Outbound drafts written from a research profile, keyed by company.
OUTREACH_DRAFTS: dict[str, dict] = {
    "Kestrel Systems": {
        "recipient": "d.reyes@kestrel-systems.example",
        "recipient_verified": True,
        "body": (
            "Hi Dana,\n\n"
            "Good to speak yesterday. Since Kestrel is at approximately $8M ARR "
            "and scaling the European operation after the Series A, the KB-88 "
            "line is built for exactly that stage.\n\n"
            "Happy to walk through it whenever suits.\n\n"
            "Alija"
        ),
    },
    "Halvard Marine": {
        "recipient": "post@halvard-marine.example",
        "recipient_verified": True,
        "body": (
            "Hello,\n\n"
            "We guarantee a 20% discount for new yard accounts, but act now - "
            "this offer expires soon.\n\n"
            "Best,\nAlija"
        ),
    },
}

#: Follow-up drafts written after a call, keyed by transcript id.
FOLLOW_UP_DRAFTS: dict[str, str] = {
    "call-001": (
        "Hi Dana,\n\n"
        "Thanks for calling. I have asked our team for the intro call times and "
        "will come back to you with options shortly.\n\n"
        "Alija"
    ),
    "call-003": (
        "Hi Jana,\n\n"
        "Sorry we were cut off. Could you let me know which order you were "
        "calling about?\n\n"
        "Alija"
    ),
}


#: The model's opinion where it differs from "nothing stands out".
JUDGEMENTS: dict[str, Judgement] = {
    # The codex sees nothing wrong here: no price, no pressure, a confirmed
    # recipient. What it cannot see is that the draft commits the organiser to
    # a specific slot before anyone has looked at the calendar.
    "dec-email-msg-004": Judgement(
        concerns=[
            "the draft names a specific time and says an invite will follow, "
            "before the calendar has been checked",
        ],
        recommend_hold=True,
        rationale=(
            "Committing to a slot that may not be free creates a second email "
            "apologising for the first."
        ),
    ),
    "dec-email-msg-001": Judgement(
        concerns=[
            "promises a pricing answer by Thursday without saying who owns it",
        ],
        recommend_hold=False,
        rationale="Reasonable to send; the commitment is soft and internal.",
    ),
}

DEFAULT_JUDGEMENT = Judgement(
    concerns=[],
    recommend_hold=False,
    rationale="Nothing stands out beyond what the codex already covers.",
)


def judge_provider(decisions: list[Decision], *, model: str = "claude-opus-5") -> MockProvider:
    """Build a provider scripted for exactly the decisions the brain will judge.

    The supervisor skips the model when the codex has already blocked a
    decision, so this mirrors that rule rather than guessing a count. If the two
    ever drift apart the mock runs out of responses and the test fails loudly,
    which is the behaviour worth having.
    """
    judged = [
        decision
        for decision in decisions
        if codex_verdict(apply_codex(decision)) is not Verdict.BLOCKED
    ]
    return MockProvider(
        [
            text_response(JUDGEMENTS.get(decision.id, DEFAULT_JUDGEMENT).model_dump_json())
            for decision in judged
        ],
        model=model,
    )
