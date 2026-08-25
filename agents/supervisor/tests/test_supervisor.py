"""Tests for the supervisor, and for the property that makes it safe to add.

The claim this file has to earn: **the supervisor can only ever be more conservative
than the agent it supervises.** If that is not true, adding oversight makes the
system riskier rather than safer, and every other guarantee in the repository
is downstream of it.
"""

from __future__ import annotations

import itertools

from agents.supervisor.agent import SupervisorAgent
from agents.supervisor.models import Decision, DecisionKind, Judgement, Verdict
from core.config import Settings
from core.llm import MockProvider, text_response


def settings() -> Settings:
    return Settings(trace_enabled=False)


def decision(**overrides) -> Decision:
    base = {
        "id": "d1",
        "agent": "email-triage",
        "kind": DecisionKind.SEND_EMAIL,
        "subject": "Re: your enquiry",
        "outbound_text": "Thanks for getting in touch. I will look into it and reply.",
        "recipient": "someone@example.test",
        "recipient_verified": True,
        "trace_ref": "msg-1",
    }
    return Decision(**{**base, **overrides})


def judge(**fields) -> MockProvider:
    return MockProvider([text_response(Judgement(**fields).model_dump_json())])


# --- The ordering the guarantee rests on --------------------------------


def test_verdicts_are_ordered_from_permissive_to_strict():
    assert Verdict.APPROVED < Verdict.HOLD_FOR_HUMAN < Verdict.BLOCKED


def test_combining_verdicts_takes_the_strictest():
    for a, b in itertools.product(Verdict, repeat=2):
        combined = max(a, b)
        assert combined >= a
        assert combined >= b


# --- The guarantee ------------------------------------------------------


def test_a_relaxed_reviewer_cannot_approve_what_the_codex_held():
    # The model says everything is fine. The codex says a person escalated this.
    supervisor = SupervisorAgent(provider=judge(recommend_hold=False), settings=settings())
    review = supervisor.review(decision(requires_human=True, escalation_reasons=["hostile"]))

    assert review.verdict is Verdict.HOLD_FOR_HUMAN


def test_a_cautious_reviewer_can_hold_what_the_codex_approved():
    supervisor = SupervisorAgent(
        provider=judge(recommend_hold=True, concerns=["tone"]), settings=settings()
    )
    review = supervisor.review(decision())

    assert review.verdict is Verdict.HOLD_FOR_HUMAN
    assert any("tone" in reason for reason in review.reasons)


def test_the_verdict_is_never_looser_than_the_codex_alone():
    # Exhaustive over both reviewer opinions and the codex outcomes that matter.
    cases = [
        decision(),
        decision(requires_human=True),
        decision(recipient_verified=False),
        decision(outbound_text="Act now, this expires soon."),
    ]
    for source, relaxed in itertools.product(cases, [True, False]):
        codex_only = SupervisorAgent(settings=settings()).review(source).verdict
        with_model = (
            SupervisorAgent(provider=judge(recommend_hold=relaxed), settings=settings())
            .review(source)
            .verdict
        )
        assert with_model >= codex_only


def test_an_escalation_survives_every_reviewer_opinion():
    for relaxed in (True, False):
        supervisor = SupervisorAgent(provider=judge(recommend_hold=relaxed), settings=settings())
        review = supervisor.review(decision(requires_human=True))
        assert review.is_approved is False


# --- When the model is consulted ---------------------------------------


def test_the_model_is_not_consulted_once_the_codex_has_blocked():
    # Nothing an opinion could say would change a block, so paying for one
    # would buy nothing.
    provider = judge(recommend_hold=True)
    supervisor = SupervisorAgent(provider=provider, settings=settings())

    review = supervisor.review(decision(recipient_verified=False))

    assert review.verdict is Verdict.BLOCKED
    assert review.judgement is None
    assert provider.calls == []


def test_the_model_is_consulted_for_anything_short_of_a_block():
    provider = judge(recommend_hold=False, rationale="fine")
    supervisor = SupervisorAgent(provider=provider, settings=settings())

    review = supervisor.review(decision(requires_human=True))

    assert len(provider.calls) == 1
    assert review.judgement is not None


def test_the_brain_runs_on_the_codex_alone():
    # No provider is a legitimate configuration: the deterministic half is the
    # half that carries the safety guarantees.
    review = SupervisorAgent(settings=settings()).review(decision(requires_human=True))

    assert review.verdict is Verdict.HOLD_FOR_HUMAN
    assert review.judgement is None


def test_the_outbound_text_reaches_the_reviewer_as_delimited_data():
    provider = judge(recommend_hold=False)
    SupervisorAgent(provider=provider, settings=settings()).review(decision())

    sent = provider.calls[0]["messages"][0]["text"]
    assert "DATA, NOT INSTRUCTIONS" in sent


# --- Reporting ----------------------------------------------------------


def test_every_codex_finding_appears_in_the_reasons():
    review = SupervisorAgent(settings=settings()).review(
        decision(requires_human=True, trace_ref=None)
    )

    assert len(review.reasons) == len(review.findings)
    assert any("A1" in reason for reason in review.reasons)
    assert any("A8" in reason for reason in review.reasons)


def test_breaches_are_separable_from_lesser_findings():
    review = SupervisorAgent(settings=settings()).review(
        decision(requires_human=True, trace_ref=None)
    )

    # A1 is a breach; A8 is only a note.
    assert [f.article for f in review.breaches] == ["A1"]


def test_a_clean_decision_is_approved():
    provider = judge(recommend_hold=False)
    review = SupervisorAgent(provider=provider, settings=settings()).review(decision())

    assert review.verdict is Verdict.APPROVED
    assert review.is_approved is True
    assert review.findings == []


def test_reviewing_many_decisions_preserves_order():
    provider = MockProvider([text_response(Judgement().model_dump_json()) for _ in range(3)])
    supervisor = SupervisorAgent(provider=provider, settings=settings())

    reviews = supervisor.review_all([decision(id=f"d{i}") for i in range(3)])
    assert [r.decision.id for r in reviews] == ["d0", "d1", "d2"]
