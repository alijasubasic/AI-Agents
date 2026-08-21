"""Tests for the knowledge base agent, citations and the demo."""

from __future__ import annotations

import pytest

from agents.knowledge_base import demo
from agents.knowledge_base.agent import (
    KnowledgeBaseAgent,
    render_answer,
    verify_citations,
)
from agents.knowledge_base.fixtures import CORPUS, QUESTIONS
from agents.knowledge_base.models import (
    Chunk,
    Citation,
    CitationStatus,
    DraftAnswer,
    Retrieval,
    ScoredChunk,
    Sufficiency,
)
from agents.knowledge_base.scripted import provider_for
from core.config import Settings
from core.llm import MockProvider, text_response


def settings() -> Settings:
    return Settings(trace_enabled=False)


def build(question_key: str) -> tuple[KnowledgeBaseAgent, MockProvider]:
    provider = provider_for(question_key)
    agent = KnowledgeBaseAgent(provider=provider, documents=CORPUS, settings=settings())
    return agent, provider


def a_retrieval(text: str = "The warranty runs 24 months from delivery.") -> Retrieval:
    chunk = Chunk(id="c1", document_id="d1", document_title="Doc", text=text, ordinal=0)
    return Retrieval(
        question="q",
        chunks=[ScoredChunk(chunk=chunk, score=0.5)],
        sufficiency=Sufficiency.SUFFICIENT,
    )


# --- Answering ----------------------------------------------------------


def test_a_well_covered_question_is_answered_with_verified_citations():
    agent, _ = build("restocking_fee")
    answer = agent.ask(QUESTIONS["restocking_fee"])

    assert answer.declined is False
    assert answer.is_grounded
    assert "15 percent" in answer.text
    assert len(answer.good_citations) == 2


def test_the_answer_names_the_documents_it_rests_on():
    agent, _ = build("restocking_fee")
    answer = agent.ask(QUESTIONS["restocking_fee"])

    assert answer.sources == ["Returns and warranty policy"]


def test_a_thinly_covered_question_is_answered_and_marked():
    agent, _ = build("warranty_scope")
    answer = agent.ask(QUESTIONS["warranty_scope"])

    assert answer.retrieval.sufficiency is Sufficiency.THIN
    assert answer.declined is False
    assert any("weakly cover" in item for item in answer.unanswered)


def test_the_model_reported_gap_survives_alongside_the_retrieval_one():
    agent, _ = build("warranty_scope")
    answer = agent.ask(QUESTIONS["warranty_scope"])

    assert any("supply agreement" in item for item in answer.unanswered)


# --- Declining ----------------------------------------------------------


def test_an_uncovered_question_is_refused():
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = KnowledgeBaseAgent(provider=provider, documents=CORPUS, settings=settings())
    answer = agent.ask(QUESTIONS["parental_leave"])

    assert answer.declined
    assert answer.retrieval.sufficiency is Sufficiency.INSUFFICIENT


def test_refusing_costs_no_model_call():
    # The whole point of the gate: for a question the corpus cannot answer, the
    # model never sees it, so it never gets the chance to invent an answer.
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = KnowledgeBaseAgent(provider=provider, documents=CORPUS, settings=settings())
    answer = agent.ask(QUESTIONS["parental_leave"])

    assert provider.calls == []
    assert answer.cost_usd == 0.0


def test_a_refusal_says_what_was_missing():
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = KnowledgeBaseAgent(provider=provider, documents=CORPUS, settings=settings())
    answer = agent.ask(QUESTIONS["parental_leave"])

    assert "parental" in answer.text
    assert "do not have enough" in answer.text


def test_a_refusal_is_rendered_not_generated():
    # The one place a model would be most tempted to be helpful.
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = KnowledgeBaseAgent(provider=provider, documents=CORPUS, settings=settings())
    first = agent.ask(QUESTIONS["parental_leave"]).text
    second = agent.ask(QUESTIONS["parental_leave"]).text

    assert first == second


# --- Citation verification ---------------------------------------------


def test_a_verbatim_quote_verifies():
    draft = DraftAnswer(
        answer="a",
        citations=[Citation(text="a", chunk_id="c1", quote="warranty runs 24 months")],
    )
    (verified,) = verify_citations(draft, a_retrieval())
    assert verified.status is CitationStatus.VERIFIED


def test_citing_a_chunk_that_was_never_retrieved_is_caught():
    draft = DraftAnswer(
        answer="a", citations=[Citation(text="a", chunk_id="c-nope", quote="anything")]
    )
    (verified,) = verify_citations(draft, a_retrieval())
    assert verified.status is CitationStatus.UNRETRIEVED
    assert verified.chunk is None


def test_citing_a_real_chunk_that_lacks_the_quote_is_caught():
    draft = DraftAnswer(
        answer="a",
        citations=[Citation(text="a", chunk_id="c1", quote="a sentence nobody wrote")],
    )
    (verified,) = verify_citations(draft, a_retrieval())

    assert verified.status is CitationStatus.UNSUPPORTED
    # The chunk is still attached so a reader can go and look.
    assert verified.chunk is not None


def test_the_two_failure_modes_are_kept_apart():
    # Inventing an id and inventing the support mean different things.
    assert CitationStatus.UNRETRIEVED is not CitationStatus.UNSUPPORTED


def test_an_empty_quote_never_verifies():
    draft = DraftAnswer(answer="a", citations=[Citation(text="a", chunk_id="c1", quote="")])
    (verified,) = verify_citations(draft, a_retrieval())
    assert verified.status is CitationStatus.UNSUPPORTED


def test_matching_survives_line_wrapping():
    retrieval = a_retrieval("The warranty runs\n  24 months from delivery.")
    draft = DraftAnswer(
        answer="a",
        citations=[Citation(text="a", chunk_id="c1", quote="warranty runs 24 months")],
    )
    (verified,) = verify_citations(draft, retrieval)
    assert verified.status is CitationStatus.VERIFIED


def test_a_misattributed_citation_is_rejected_end_to_end():
    # The scripted answer attributes a support-document fact to the returns
    # document. The fact is right; the attribution is not.
    agent, _ = build("key_account_response")
    answer = agent.ask(QUESTIONS["key_account_response"])

    assert len(answer.bad_citations) == 1
    assert answer.bad_citations[0].status is CitationStatus.UNSUPPORTED
    assert answer.is_grounded is False


# --- Rendering ----------------------------------------------------------


def test_the_rendered_answer_lists_verified_sources():
    agent, _ = build("restocking_fee")
    text = render_answer(agent.ask(QUESTIONS["restocking_fee"]))

    assert "## Sources" in text
    assert "doc-returns#0" in text


def test_rejected_citations_get_their_own_section():
    agent, _ = build("key_account_response")
    text = render_answer(agent.ask(QUESTIONS["key_account_response"]))

    assert "## Unverified citations" in text
    assert "unsupported" in text


def test_a_refusal_renders_without_a_sources_section():
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = KnowledgeBaseAgent(provider=provider, documents=CORPUS, settings=settings())
    text = render_answer(agent.ask(QUESTIONS["parental_leave"]))

    assert "## Sources" not in text
    assert "insufficient" in text


def test_rendering_is_deterministic():
    agent, _ = build("restocking_fee")
    answer = agent.ask(QUESTIONS["restocking_fee"])
    assert render_answer(answer) == render_answer(answer)


# --- Demo ---------------------------------------------------------------


def test_the_demo_asks_every_fixture_question():
    assert len(demo.ask_all(settings())) == len(QUESTIONS)


def test_the_demo_covers_every_sufficiency_verdict():
    verdicts = {a.retrieval.sufficiency for a in demo.ask_all(settings())}
    assert verdicts == set(Sufficiency)


def test_the_demo_shows_a_rejected_citation():
    # A verifier nobody has watched reject something is one nobody should trust.
    assert any(a.bad_citations for a in demo.ask_all(settings()))


def test_no_declined_answer_carries_citations():
    for answer in demo.ask_all(settings()):
        if answer.declined:
            assert answer.citations == []


def test_scripted_answers_exist_only_for_questions_that_reach_the_model():
    # parental_leave is refused before the model, so scripting it would be dead
    # weight that quietly rots.
    with pytest.raises(KeyError):
        provider_for("parental_leave")


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "knowledge-base demo" in output
    assert "REFUSED" in output
