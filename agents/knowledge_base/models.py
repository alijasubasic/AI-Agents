"""Data models for the knowledge base agent.

Retrieval-augmented generation fails in a characteristic way: the retriever
returns the three least-irrelevant chunks it has, the model writes a confident
answer from them, and nothing anywhere notices that the corpus never contained
the answer. The failure looks exactly like a success.

Two things in these models exist to stop that:

* `Retrieval` carries a **sufficiency** verdict decided by code, before the
  model is asked anything. "I don't know" is an outcome the system produces,
  not a behaviour it hopes the model chooses.
* Every sentence of an answer carries a `Citation`, and each citation is
  checked against the chunk it names.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Document(BaseModel):
    """One source document in the corpus."""

    id: str
    title: str
    source: str = Field(default="", description="Where this came from: a path, a URL, a ticket.")
    text: str

    @property
    def label(self) -> str:
        return f"{self.title} ({self.source})" if self.source else self.title


class Chunk(BaseModel):
    """A retrievable slice of a document."""

    id: str
    document_id: str
    document_title: str
    text: str

    #: Position in the document, so a citation can say "third section of X".
    ordinal: int = 0

    @property
    def preview(self) -> str:
        flat = " ".join(self.text.split())
        return flat[:96] + ("…" if len(flat) > 96 else "")


class ScoredChunk(BaseModel):
    """A chunk with its similarity to the question."""

    chunk: Chunk
    score: float

    @property
    def id(self) -> str:
        return self.chunk.id


class Sufficiency(StrEnum):
    """Whether the retrieved context can support an answer at all.

    Decided in `retrieval.py` by looking at similarity and term coverage — not
    by asking the model whether it feels able to answer, which is a question
    models are notoriously bad at.
    """

    #: Enough support. The model may answer.
    SUFFICIENT = "sufficient"

    #: Something was retrieved but it is weak or only partly covers the
    #: question. The model may answer, and the answer is marked as partial.
    THIN = "thin"

    #: Nothing retrieved clears the floor. The agent answers "I don't know"
    #: without consulting the model at all.
    INSUFFICIENT = "insufficient"


class Retrieval(BaseModel):
    """What the retriever found, and what it concluded about it."""

    question: str
    chunks: list[ScoredChunk] = Field(default_factory=list)
    sufficiency: Sufficiency = Sufficiency.INSUFFICIENT
    reason: str = ""

    #: Question terms no retrieved chunk contains. The most useful thing to
    #: show a person when an answer comes back thin.
    uncovered_terms: list[str] = Field(default_factory=list)

    @property
    def may_answer(self) -> bool:
        return self.sufficiency is not Sufficiency.INSUFFICIENT

    @property
    def chunk_ids(self) -> list[str]:
        return [scored.id for scored in self.chunks]

    @property
    def top_score(self) -> float:
        return self.chunks[0].score if self.chunks else 0.0


class Citation(BaseModel):
    """One claim in an answer, with the chunk it came from.

    Field descriptions are prompt text — this is the schema the model fills in.
    """

    text: str = Field(description="One sentence of the answer.")
    chunk_id: str = Field(
        description=(
            "The id of the retrieved chunk supporting this sentence, exactly as "
            "given. Every sentence needs one; if no chunk supports a sentence, "
            "do not write that sentence."
        )
    )
    quote: str = Field(
        description=(
            "The exact span from that chunk supporting the sentence, copied "
            "verbatim. It is checked against the chunk, so a paraphrase fails."
        )
    )


class DraftAnswer(BaseModel):
    """What the model returns."""

    answer: str = Field(description="The answer, in two or three sentences.")
    citations: list[Citation] = Field(
        default_factory=list, description="One entry per sentence of the answer."
    )
    unanswered: list[str] = Field(
        default_factory=list,
        description=(
            "Parts of the question the retrieved context does not cover. Naming "
            "a gap is more useful than filling it."
        ),
    )


class CitationStatus(StrEnum):
    VERIFIED = "verified"
    #: Cites a chunk that was never retrieved.
    UNRETRIEVED = "unretrieved"
    #: Cites a retrieved chunk that does not contain the quote.
    UNSUPPORTED = "unsupported"


class VerifiedCitation(BaseModel):
    citation: Citation
    status: CitationStatus
    chunk: Chunk | None = None

    @property
    def is_good(self) -> bool:
        return self.status is CitationStatus.VERIFIED


class Answer(BaseModel):
    """The final result of a question."""

    question: str
    retrieval: Retrieval

    text: str = ""
    citations: list[VerifiedCitation] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)

    #: True when the agent declined to answer. Not a failure — for a question
    #: the corpus cannot answer, it is the only correct outcome.
    declined: bool = False

    cost_usd: float = 0.0
    duration_ms: float = 0.0

    @property
    def good_citations(self) -> list[VerifiedCitation]:
        return [c for c in self.citations if c.is_good]

    @property
    def bad_citations(self) -> list[VerifiedCitation]:
        return [c for c in self.citations if not c.is_good]

    @property
    def is_grounded(self) -> bool:
        """Whether every citation survived verification."""
        return bool(self.citations) and not self.bad_citations

    @property
    def sources(self) -> list[str]:
        """Distinct documents the answer actually rests on."""
        seen: list[str] = []
        for verified in self.good_citations:
            if verified.chunk and verified.chunk.document_title not in seen:
                seen.append(verified.chunk.document_title)
        return seen
