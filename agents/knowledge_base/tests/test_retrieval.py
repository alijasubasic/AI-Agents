"""Tests for chunking, embedding and the sufficiency gate.

None of this involves a model, which is the point: whether the corpus can
support an answer is decided by code, before anything is asked.
"""

from __future__ import annotations

import pytest

from agents.knowledge_base.chunking import (
    chunk_corpus,
    chunk_document,
    split_sentences,
)
from agents.knowledge_base.embedding import LexicalEmbedder, cosine, tokenise
from agents.knowledge_base.fixtures import CORPUS, QUESTIONS
from agents.knowledge_base.models import Chunk, Document, ScoredChunk, Sufficiency
from agents.knowledge_base.retrieval import (
    VectorIndex,
    assess,
    retrieve,
    separation,
    term_coverage,
)


def document(text: str, doc_id: str = "d1") -> Document:
    return Document(id=doc_id, title="Test document", source="test.md", text=text)


def scored(*values: float) -> list[ScoredChunk]:
    return [
        ScoredChunk(
            chunk=Chunk(
                id=f"c{i}",
                document_id="d",
                document_title="D",
                text="policy text about warranty",
                ordinal=i,
            ),
            score=value,
        )
        for i, value in enumerate(values)
    ]


# --- Chunking -----------------------------------------------------------


def test_a_short_document_is_one_chunk():
    chunks = chunk_document(document("One short paragraph."))
    assert len(chunks) == 1
    assert chunks[0].text == "One short paragraph."


def test_chunk_ids_are_stable_across_runs():
    # A citation written last week has to still resolve.
    first = [c.id for c in chunk_corpus(CORPUS)]
    second = [c.id for c in chunk_corpus(CORPUS)]
    assert first == second
    assert first[0] == "doc-returns#0"


def test_no_chunk_exceeds_the_limit():
    for chunk in chunk_corpus(CORPUS, max_chars=300):
        assert len(chunk.text) <= 300


def test_chunks_carry_their_document():
    chunk = chunk_corpus(CORPUS)[0]
    assert chunk.document_id == "doc-returns"
    assert chunk.document_title == "Returns and warranty policy"


def test_chunks_overlap_by_whole_sentences():
    # An answer sitting across a boundary is the classic RAG failure, and
    # overlapping by characters would cut sentences in half to fix it.
    text = "\n\n".join(f"Sentence number {i} says something useful." for i in range(20))
    chunks = chunk_document(document(text), max_chars=200, overlap_chars=60)

    assert len(chunks) > 1
    overlap = set(split_sentences(chunks[0].text)) & set(split_sentences(chunks[1].text))
    assert overlap


def test_a_single_oversized_sentence_is_split_rather_than_dropped():
    chunks = chunk_document(document("word " * 400), max_chars=200)
    assert chunks
    assert all(len(c.text) <= 200 for c in chunks)


def test_an_empty_document_produces_nothing():
    assert chunk_document(document("   \n\n  ")) == []


def test_nonsensical_settings_are_refused():
    with pytest.raises(ValueError, match="max_chars"):
        chunk_document(document("text"), max_chars=0)
    with pytest.raises(ValueError, match="overlap"):
        chunk_document(document("text"), max_chars=100, overlap_chars=100)


# --- Embedding ----------------------------------------------------------


def test_stop_words_are_dropped_but_negations_are_kept():
    tokens = tokenise("What is the notice period, and is it not extended?")
    assert "the" not in tokens
    # An aggressive stop list would remove "not", which changes the meaning of
    # every policy sentence it appears in.
    assert "not" in tokens


def test_identical_text_is_perfectly_similar():
    embedder = LexicalEmbedder()
    embedder.fit(["warranty covers defects", "shipping takes two days"])
    vector = embedder.embed("warranty covers defects")
    assert cosine(vector, vector) == pytest.approx(1.0)


def test_unrelated_text_scores_zero():
    embedder = LexicalEmbedder()
    embedder.fit(["warranty covers defects", "shipping takes two days"])
    assert cosine(embedder.embed("warranty"), embedder.embed("shipping")) == 0.0


def test_an_empty_query_matches_nothing():
    embedder = LexicalEmbedder()
    embedder.fit(["some text"])
    assert embedder.embed("the and of") == {}


def test_refitting_replaces_rather_than_accumulates():
    embedder = LexicalEmbedder()
    embedder.fit(["one", "two", "three"])
    embedder.fit(["four"])
    assert embedder.document_count == 1


# --- Ranking ------------------------------------------------------------


def test_the_index_returns_the_relevant_chunk_first():
    index = VectorIndex().index(chunk_corpus(CORPUS))
    results = index.search("restocking fee on opened stock")
    assert results[0].chunk.document_id == "doc-returns"


def test_ranking_is_deterministic():
    index = VectorIndex().index(chunk_corpus(CORPUS))
    question = QUESTIONS["restocking_fee"]
    assert [s.id for s in index.search(question)] == [s.id for s in index.search(question)]


def test_top_k_is_respected():
    index = VectorIndex().index(chunk_corpus(CORPUS))
    assert len(index.search("warranty shipping support onboarding", top_k=2)) <= 2


def test_zero_scoring_chunks_are_not_returned():
    index = VectorIndex().index(chunk_corpus(CORPUS))
    assert all(s.score > 0 for s in index.search("restocking"))


def test_an_empty_index_returns_nothing():
    assert VectorIndex().search("anything") == []


# --- The gate -----------------------------------------------------------


def test_nothing_retrieved_is_insufficient():
    verdict = assess("a question", [])
    assert verdict.sufficiency is Sufficiency.INSUFFICIENT
    assert verdict.may_answer is False


def test_noise_is_refused():
    verdict = assess("warranty policy text", scored(0.04, 0.03))
    assert verdict.sufficiency is Sufficiency.INSUFFICIENT
    assert "noise floor" in verdict.reason


def test_a_flat_field_is_refused():
    # Every chunk equally mediocre means the corpus mentions the words without
    # answering the question.
    verdict = assess("warranty policy text", scored(0.20, 0.19, 0.18))
    assert verdict.sufficiency is Sufficiency.INSUFFICIENT
    assert "stands out" in verdict.reason


def test_a_clear_winner_is_accepted():
    verdict = assess("warranty policy text", scored(0.40, 0.05, 0.04))
    assert verdict.may_answer


def test_a_single_result_counts_as_separated():
    # Nothing contradicted it.
    assert separation(scored(0.5)) == float("inf")


def test_separation_is_the_ratio_to_the_rest():
    assert separation(scored(0.4, 0.1, 0.1)) == pytest.approx(4.0)


def test_missing_question_terms_are_reported():
    coverage, uncovered = term_coverage("warranty parental leave", scored(0.5))
    assert coverage < 1.0
    assert "parental" in uncovered


def test_the_gate_is_not_fooled_by_question_length():
    # The regression this design exists for: TF-IDF cosine falls as a question
    # gets longer, so an absolute threshold punishes full sentences. Both of
    # these ask the same thing.
    index = VectorIndex().index(chunk_corpus(CORPUS))
    short = retrieve(index, "restocking fee?")
    long = retrieve(
        index,
        "Could you tell me what restocking fee applies when a customer returns opened stock to us?",
    )
    assert short.may_answer
    assert long.may_answer


# --- Against the fixture corpus ----------------------------------------


def test_every_fixture_question_reaches_its_intended_verdict():
    index = VectorIndex().index(chunk_corpus(CORPUS))
    verdicts = {key: retrieve(index, q).sufficiency for key, q in QUESTIONS.items()}

    assert verdicts["restocking_fee"] is Sufficiency.SUFFICIENT
    assert verdicts["key_account_response"] is Sufficiency.SUFFICIENT
    assert verdicts["warranty_scope"] is Sufficiency.THIN
    assert verdicts["parental_leave"] is Sufficiency.INSUFFICIENT


def test_an_off_topic_question_names_what_is_missing():
    index = VectorIndex().index(chunk_corpus(CORPUS))
    verdict = retrieve(index, QUESTIONS["parental_leave"])

    assert verdict.may_answer is False
    assert "parental" in verdict.uncovered_terms
