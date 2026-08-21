"""Retrieval, and the gate that decides whether an answer is possible at all.

The gate is the point of this module.

A retriever always returns something. Ask a corpus of HR policies about
shipping rates and it will hand back the three least-irrelevant paragraphs it
has, because "least irrelevant" is the only thing a similarity search can
compute. Pass those to a model with "answer the question" and you get a
confident, well-cited, entirely invented answer — and the failure is invisible,
because it has exactly the shape of a success.

So `assess` runs before the model is consulted, and it can refuse. "I don't
know" is a verdict this code reaches, not a behaviour the prompt asks for.
"""

from __future__ import annotations

from agents.knowledge_base.embedding import (
    EmbeddingProvider,
    LexicalEmbedder,
    cosine,
    tokenise,
)
from agents.knowledge_base.models import (
    Chunk,
    Retrieval,
    ScoredChunk,
    Sufficiency,
)

#: Below this, the best match is noise rather than a weak answer. Kept low
#: deliberately — it is a floor under nonsense, not the main decision.
NOISE_FLOOR = 0.10

#: How far the best match must stand out from the rest of the field.
#:
#: This is the primary signal, and it replaced an absolute similarity threshold
#: that turned out to be the wrong shape. TF-IDF cosine falls as a question
#: gets longer, because extra terms dilute the query vector — so a fixed floor
#: quietly punishes people for asking in full sentences. A well-answered
#: question instead shows one chunk clearly ahead of the others, whatever the
#: absolute numbers are, and that ratio is stable across question lengths.
MIN_SEPARATION = 1.5

#: Fraction of the question's meaningful terms that must appear somewhere in
#: the retrieved text. Similarity alone is not enough — a chunk can score
#: respectably while missing the one word the question is actually about.
MIN_TERM_COVERAGE = 0.5

#: Clear both of these and the answer is not marked thin.
STRONG_SEPARATION = 2.5
STRONG_TERM_COVERAGE = 0.75

DEFAULT_TOP_K = 4


class VectorIndex:
    """An in-memory index over chunks.

    Small enough to be honest about: this is a linear scan. For a few thousand
    chunks that is microseconds and needs no dependency; for a few million it
    would need a real vector store, which is a different project.
    """

    def __init__(self, embedder: EmbeddingProvider | None = None) -> None:
        self.embedder = embedder or LexicalEmbedder()
        self.chunks: list[Chunk] = []
        self._vectors: list[dict[str, float]] = []

    def index(self, chunks: list[Chunk]) -> VectorIndex:
        """Index a set of chunks, replacing anything already held."""
        self.chunks = list(chunks)
        self.embedder.fit([chunk.text for chunk in self.chunks])
        self._vectors = [self.embedder.embed(chunk.text) for chunk in self.chunks]
        return self

    def search(self, question: str, *, top_k: int = DEFAULT_TOP_K) -> list[ScoredChunk]:
        """The `top_k` most similar chunks, best first.

        Ties break on chunk order rather than arbitrarily, so an unchanged
        corpus always returns the same ranking and an eval can assert on it.
        """
        if not self.chunks:
            return []

        query = self.embedder.embed(question)
        scored = [
            ScoredChunk(chunk=chunk, score=cosine(query, vector))
            for chunk, vector in zip(self.chunks, self._vectors, strict=True)
        ]
        scored.sort(key=lambda item: (-item.score, item.chunk.ordinal, item.chunk.id))
        return [item for item in scored[:top_k] if item.score > 0.0]

    def __len__(self) -> int:
        return len(self.chunks)


def term_coverage(question: str, chunks: list[ScoredChunk]) -> tuple[float, list[str]]:
    """What fraction of the question's terms appear in the retrieved text.

    Returns the fraction and the terms nobody covered — which is the single
    most useful thing to show a person when an answer comes back thin.
    """
    terms = set(tokenise(question))
    if not terms:
        return 1.0, []

    haystack = " ".join(scored.chunk.text for scored in chunks).lower()
    present = {term for term in terms if term in haystack}
    uncovered = sorted(terms - present)
    return len(present) / len(terms), uncovered


def separation(chunks: list[ScoredChunk]) -> float:
    """How far the best match stands out from the rest of the field.

    The ratio of the top score to the mean of the others. A single result
    counts as well separated: nothing contradicted it.
    """
    if not chunks:
        return 0.0
    rest = [scored.score for scored in chunks[1:]]
    if not rest:
        return float("inf")

    mean_rest = sum(rest) / len(rest)
    if mean_rest <= 0:
        return float("inf")
    return chunks[0].score / mean_rest


def assess(
    question: str,
    chunks: list[ScoredChunk],
    *,
    noise_floor: float = NOISE_FLOOR,
    min_separation: float = MIN_SEPARATION,
    min_coverage: float = MIN_TERM_COVERAGE,
) -> Retrieval:
    """Decide whether the retrieved context can support an answer."""
    coverage, uncovered = term_coverage(question, chunks)
    top = chunks[0].score if chunks else 0.0
    apart = separation(chunks)

    def verdict(sufficiency: Sufficiency, reason: str) -> Retrieval:
        return Retrieval(
            question=question,
            chunks=chunks,
            sufficiency=sufficiency,
            reason=reason,
            uncovered_terms=uncovered,
        )

    if not chunks:
        return verdict(Sufficiency.INSUFFICIENT, "nothing in the corpus matched the question")

    if top < noise_floor:
        return verdict(
            Sufficiency.INSUFFICIENT,
            f"best match scored {top:.2f}, below the {noise_floor:.2f} noise floor; "
            f"the corpus does not appear to cover this",
        )

    if apart < min_separation:
        return verdict(
            Sufficiency.INSUFFICIENT,
            f"no passage stands out ({apart:.1f}x the rest of the field); the "
            f"corpus mentions these words without answering the question",
        )

    if coverage < min_coverage:
        return verdict(
            Sufficiency.INSUFFICIENT,
            f"only {coverage:.0%} of the question's terms appear in the retrieved "
            f"text; missing: {', '.join(uncovered[:4])}",
        )

    if apart < STRONG_SEPARATION or coverage < STRONG_TERM_COVERAGE:
        return verdict(
            Sufficiency.THIN,
            f"supported but weakly: best match {top:.2f}, "
            f"{apart:.1f}x separation, {coverage:.0%} term coverage",
        )

    return verdict(
        Sufficiency.SUFFICIENT,
        f"best match {top:.2f}, {apart:.1f}x separation, {coverage:.0%} term coverage",
    )


def retrieve(index: VectorIndex, question: str, *, top_k: int = DEFAULT_TOP_K) -> Retrieval:
    """Search and assess in one step."""
    return assess(question, index.search(question, top_k=top_k))
