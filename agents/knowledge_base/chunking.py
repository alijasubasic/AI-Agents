"""Splitting documents into retrievable chunks.

Deterministic, dependency-free, and boring on purpose: the same document always
produces the same chunks with the same ids, which is what makes a retrieval
regression visible rather than mysterious.

Two rules shape the algorithm:

* **Split on paragraph boundaries first.** A chunk that begins mid-sentence
  reads as nonsense when quoted back to a user as a citation, which is the one
  place chunks are seen by a human.
* **Overlap by whole sentences.** An answer sitting across a boundary is the
  classic RAG failure. Overlapping by characters instead would cut sentences in
  half and reintroduce the first problem to solve the second.
"""

from __future__ import annotations

import re

from agents.knowledge_base.models import Chunk, Document

#: Target chunk size in characters. Small enough that a citation quote is
#: findable by eye, large enough to hold a whole policy paragraph.
DEFAULT_MAX_CHARS = 700

#: How much of the previous chunk's tail to repeat at the start of the next.
DEFAULT_OVERLAP_CHARS = 120

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split on sentence endings. Crude, and adequate for the job.

    A real sentence tokeniser would handle "Dr." and "e.g." correctly. The cost
    of getting those wrong here is a chunk boundary in a slightly odd place,
    which is not worth a dependency.
    """
    return [part.strip() for part in _SENTENCE_END.split(text.strip()) if part.strip()]


def _tail(text: str, chars: int) -> str:
    """The last whole sentences of `text`, within `chars` characters.

    Returns nothing when not even one whole sentence fits. Truncating to the
    budget would produce a fragment starting mid-word, which is worse than no
    overlap at all — and overlap exists to make citations readable.
    """
    if chars <= 0:
        return ""

    kept: list[str] = []
    length = 0
    for sentence in reversed(split_sentences(text)):
        if length + len(sentence) > chars:
            break
        kept.insert(0, sentence)
        length += len(sentence) + 1
    return " ".join(kept)


def chunk_document(
    document: Document,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Split one document into overlapping chunks.

    Ids are `{document_id}#{ordinal}` and depend only on the document and the
    settings, so re-indexing an unchanged corpus produces identical ids and a
    citation written last week still resolves.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    paragraphs = [p.strip() for p in _PARAGRAPH.split(document.text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        for piece in _fit(paragraph, max_chars):
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if len(candidate) <= max_chars:
                current = candidate
                continue

            if current:
                chunks.append(current)
                # The size limit is a guarantee; the overlap is a nicety. When
                # the two conflict the overlap is dropped, because a chunk over
                # the limit breaks whatever the limit was protecting.
                overlap = _tail(current, overlap_chars)
                with_overlap = f"{overlap}\n\n{piece}".strip()
                current = with_overlap if overlap and len(with_overlap) <= max_chars else piece
            else:
                current = piece

    if current:
        chunks.append(current)

    return [
        Chunk(
            id=f"{document.id}#{ordinal}",
            document_id=document.id,
            document_title=document.title,
            text=text,
            ordinal=ordinal,
        )
        for ordinal, text in enumerate(chunks)
    ]


def _fit(paragraph: str, max_chars: int) -> list[str]:
    """Break a paragraph that exceeds the limit on its own, at sentence ends."""
    if len(paragraph) <= max_chars:
        return [paragraph]

    pieces: list[str] = []
    current = ""
    for sentence in split_sentences(paragraph):
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                pieces.append(current)
            # A single sentence longer than the limit is split by characters.
            # Nothing better is available, and it is rare enough to accept.
            while len(sentence) > max_chars:
                pieces.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            current = sentence

    if current:
        pieces.append(current)
    return pieces


def chunk_corpus(
    documents: list[Document],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Chunk every document, preserving corpus order."""
    return [
        chunk
        for document in documents
        for chunk in chunk_document(document, max_chars=max_chars, overlap_chars=overlap_chars)
    ]
