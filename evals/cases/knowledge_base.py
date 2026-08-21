"""Eval cases for the knowledge base agent.

The sufficiency gate and the citation verifier are both deterministic, so both
can be scored exactly. The gaps at the bottom are where lexical retrieval
stops working, which is the honest cost of keeping the whole thing offline.
"""

from __future__ import annotations

from agents.knowledge_base.agent import KnowledgeBaseAgent
from agents.knowledge_base.chunking import chunk_corpus
from agents.knowledge_base.fixtures import CORPUS, QUESTIONS
from agents.knowledge_base.models import CitationStatus, Sufficiency
from agents.knowledge_base.retrieval import VectorIndex, retrieve
from agents.knowledge_base.scripted import provider_for
from core.config import Settings
from core.llm import MockProvider, text_response
from evals.models import Expectation, Layer, Score
from evals.registry import case
from evals.scoring import combine, contains_all, equals, is_false, is_true

AGENT = "knowledge-base"


def _index() -> VectorIndex:
    return VectorIndex().index(chunk_corpus(CORPUS))


def _ask(question_key: str):
    agent = KnowledgeBaseAgent(
        provider=provider_for(question_key),
        documents=CORPUS,
        settings=Settings(trace_enabled=False),
    )
    return agent.ask(QUESTIONS[question_key])


def _ask_refused(question_key: str):
    provider = MockProvider([text_response("{}")], model="claude-opus-5")
    agent = KnowledgeBaseAgent(
        provider=provider, documents=CORPUS, settings=Settings(trace_enabled=False)
    )
    return agent.ask(QUESTIONS[question_key]), provider


# --- The gate -----------------------------------------------------------


@case(
    id="kb-refuses-what-the-corpus-does-not-cover",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An off-topic question is declined rather than answered from noise.",
)
def _() -> Score:
    answer, _provider = _ask_refused("parental_leave")
    return combine(
        is_true(answer.declined, label="declined"),
        equals(answer.retrieval.sufficiency, Sufficiency.INSUFFICIENT, label="verdict"),
    )


@case(
    id="kb-refusal-costs-nothing",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A refused question never reaches the model.",
)
def _() -> Score:
    answer, provider = _ask_refused("parental_leave")
    return combine(
        equals(provider.calls, [], label="model calls"),
        equals(answer.cost_usd, 0.0, label="cost"),
    )


@case(
    id="kb-refusal-names-what-is-missing",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The decline says which terms nothing covered.",
)
def _() -> Score:
    answer, _ = _ask_refused("parental_leave")
    return contains_all(answer.text, ["parental", "leave"], label="refusal text")


@case(
    id="kb-covered-question-is-answered",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A well-covered question gets a grounded answer.",
)
def _() -> Score:
    answer = _ask("restocking_fee")
    return combine(
        is_false(answer.declined, label="declined"),
        is_true(answer.is_grounded, label="grounded"),
        contains_all(answer.text, ["15 percent", "14 days"], label="answer"),
    )


@case(
    id="kb-thin-coverage-is-marked-not-hidden",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A weakly supported answer says so rather than reading as confident.",
)
def _() -> Score:
    answer = _ask("warranty_scope")
    return combine(
        equals(answer.retrieval.sufficiency, Sufficiency.THIN, label="verdict"),
        is_true(
            any("weakly cover" in item for item in answer.unanswered),
            label="marked thin",
        ),
    )


@case(
    id="kb-gate-is-insensitive-to-question-length",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The same question asked briefly and at length both pass the gate.",
)
def _() -> Score:
    index = _index()
    short = retrieve(index, "restocking fee?")
    long = retrieve(
        index,
        "Could you tell me what restocking fee applies when a customer returns opened stock to us?",
    )
    return combine(
        is_true(short.may_answer, label="short question answerable"),
        is_true(long.may_answer, label="long question answerable"),
    )


@case(
    id="kb-flat-field-is-refused",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="When every chunk scores alike, the corpus mentions the words without answering.",
)
def _() -> Score:
    # Generic policy vocabulary appearing in all four documents. The best match
    # is only 1.2x the rest of the field, which is what "mentioned everywhere,
    # answered nowhere" looks like numerically.
    verdict = retrieve(_index(), "days working policy support")
    return is_false(verdict.may_answer, label="answerable")


# --- Citations ----------------------------------------------------------


@case(
    id="kb-verbatim-citations-verify",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Quotes copied from the chunk pass verification.",
)
def _() -> Score:
    answer = _ask("restocking_fee")
    return combine(
        equals(len(answer.good_citations), 2, label="verified citations"),
        equals(answer.bad_citations, [], label="rejected citations"),
    )


@case(
    id="kb-misattributed-citation-is-rejected",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A true fact attributed to the wrong document is caught.",
)
def _() -> Score:
    answer = _ask("key_account_response")
    bad = answer.bad_citations
    return combine(
        equals(len(bad), 1, label="rejected citations"),
        equals(bad[0].status, CitationStatus.UNSUPPORTED, label="status"),
        is_false(answer.is_grounded, label="grounded"),
    )


@case(
    id="kb-sources-list-only-verified-documents",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A document reached only by a rejected citation is not listed as a source.",
)
def _() -> Score:
    answer = _ask("key_account_response")
    return equals(answer.sources, ["Support tiers and response times"], label="sources")


# --- Chunking and ranking ----------------------------------------------


@case(
    id="kb-chunk-ids-are-stable",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Re-indexing an unchanged corpus produces identical ids.",
)
def _() -> Score:
    return equals(
        [c.id for c in chunk_corpus(CORPUS)],
        [c.id for c in chunk_corpus(CORPUS)],
        label="chunk ids",
    )


@case(
    id="kb-ranking-is-deterministic",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The same question returns the same ranking every time.",
)
def _() -> Score:
    index = _index()
    question = QUESTIONS["restocking_fee"]
    return equals(
        [s.id for s in index.search(question)],
        [s.id for s in index.search(question)],
        label="ranking",
    )


@case(
    id="kb-retrieves-the-right-document",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A support question ranks the support document first.",
)
def _() -> Score:
    top = _index().search(QUESTIONS["key_account_response"])[0]
    return equals(top.chunk.document_id, "doc-support", label="top document")


# --- Known gaps ---------------------------------------------------------


@case(
    id="kb-retrieval-is-lexical-not-semantic",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A question sharing no words with the answer retrieves nothing.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "TF-IDF finds documents sharing words with the question. 'How much "
        "warning must a customer give before sending something back' is the "
        "returns policy asked in different words, and scores near zero. A "
        "hosted embedding model would find it; keeping retrieval offline costs "
        "exactly this."
    ),
)
def _() -> Score:
    verdict = retrieve(_index(), "How much notice must someone give before sending an item back?")
    return is_true(verdict.may_answer, label="paraphrased question answerable")


@case(
    id="kb-no-stemming",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="'exclude' and 'excludes' are different terms to the retriever.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Visible in the demo: the warranty question is marked THIN partly "
        "because 'exclude' does not match 'excludes' in the document. A stemmer "
        "would fix it in about ten lines and has not been added."
    ),
)
def _() -> Score:
    answer = _ask("warranty_scope")
    return is_false("exclude" in answer.retrieval.uncovered_terms, label="stem matched")


@case(
    id="kb-citations-checked-for-existence-not-entailment",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A real quote supporting a wrong sentence still verifies.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Same limitation as lead-research, one level down. The verifier asks "
        "whether the span exists in the chunk, not whether the sentence follows "
        "from it. A citation whose quote is real and whose claim is wrong "
        "passes."
    ),
)
def _() -> Score:
    from agents.knowledge_base.agent import verify_citations
    from agents.knowledge_base.models import Chunk, Citation, DraftAnswer, ScoredChunk

    chunk = Chunk(
        id="c1",
        document_id="d",
        document_title="D",
        text="Standard support is available Monday to Friday, 09:00 to 17:00 CET.",
        ordinal=0,
    )
    retrieval_stub = _index().search(QUESTIONS["restocking_fee"])[0]
    _ = retrieval_stub  # ranking is exercised elsewhere; this case is about entailment

    from agents.knowledge_base.models import Retrieval

    draft = DraftAnswer(
        answer="Support is available 24/7.",
        citations=[
            Citation(
                text="Support is available 24/7.",
                chunk_id="c1",
                quote="Standard support is available Monday to Friday",
            )
        ],
    )
    (verified,) = verify_citations(
        draft,
        Retrieval(
            question="q",
            chunks=[ScoredChunk(chunk=chunk, score=0.5)],
            sufficiency=Sufficiency.SUFFICIENT,
        ),
    )
    return is_false(verified.is_good, label="contradicted claim rejected")
