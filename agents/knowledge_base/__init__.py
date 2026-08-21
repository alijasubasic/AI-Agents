"""Knowledge base: answer from customer documents, with citations, or decline.

"I don't know" is an outcome the retriever reaches in code, before the model is
consulted — not a behaviour the prompt asks the model to choose.
"""

from agents.knowledge_base.agent import (
    KnowledgeBaseAgent,
    render_answer,
    verify_citations,
)
from agents.knowledge_base.chunking import chunk_corpus, chunk_document, split_sentences
from agents.knowledge_base.embedding import (
    EmbeddingProvider,
    LexicalEmbedder,
    VoyageEmbedder,
    build_embedder,
    cosine,
    tokenise,
)
from agents.knowledge_base.models import (
    Answer,
    Chunk,
    Citation,
    CitationStatus,
    Document,
    DraftAnswer,
    Retrieval,
    ScoredChunk,
    Sufficiency,
    VerifiedCitation,
)
from agents.knowledge_base.retrieval import (
    VectorIndex,
    assess,
    retrieve,
    separation,
    term_coverage,
)

__all__ = [
    "Answer",
    "Chunk",
    "Citation",
    "CitationStatus",
    "Document",
    "DraftAnswer",
    "EmbeddingProvider",
    "KnowledgeBaseAgent",
    "LexicalEmbedder",
    "Retrieval",
    "ScoredChunk",
    "Sufficiency",
    "VectorIndex",
    "VerifiedCitation",
    "VoyageEmbedder",
    "assess",
    "build_embedder",
    "chunk_corpus",
    "chunk_document",
    "cosine",
    "render_answer",
    "retrieve",
    "separation",
    "split_sentences",
    "term_coverage",
    "tokenise",
    "verify_citations",
]
