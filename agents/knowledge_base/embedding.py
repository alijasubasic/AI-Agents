"""Turning text into vectors.

One `Protocol`, a local implementation that works offline, and a hosted one.
Unlike the other providers in this repository, the default here is not a mock
pretending to be a real service — `LexicalEmbedder` is a genuine retriever. It
is simply a lexical one.

That distinction matters and is stated plainly in the README: TF-IDF over
character-folded tokens finds documents that share *words* with the question.
It will not find a document about "notice period" when the question says
"how much warning do I have to give". A hosted embedding model would. Nothing
here pretends otherwise.

The trade is deliberate. A local retriever keeps the "clone it and run it"
promise, makes every eval score exact, and is honest about what it does.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Protocol

_TOKEN = re.compile(r"[a-z0-9]+")

#: Words carrying no retrieval signal. Kept short on purpose: an aggressive
#: stop list removes terms that matter in a policy corpus ("no", "not", "all").
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)


def tokenise(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stop words removed."""
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


class EmbeddingProvider(Protocol):
    """Turns text into a sparse or dense vector."""

    def embed(self, text: str) -> dict[str, float]: ...

    def fit(self, corpus: list[str]) -> None: ...


class LexicalEmbedder:
    """TF-IDF vectors over the corpus. Real retrieval, no network, no model.

    Sparse dictionaries rather than dense arrays: the vocabulary of a document
    corpus is large and each document touches a tiny slice of it, so a dict is
    both smaller and faster here than a list of mostly-zeros — and it needs no
    numpy.
    """

    def __init__(self) -> None:
        self.document_frequency: Counter[str] = Counter()
        self.document_count = 0

    def fit(self, corpus: list[str]) -> None:
        """Learn document frequencies. Idempotent: refitting replaces, not adds."""
        self.document_frequency = Counter()
        self.document_count = len(corpus)
        for text in corpus:
            for token in set(tokenise(text)):
                self.document_frequency[token] += 1

    def _idf(self, token: str) -> float:
        """Smoothed inverse document frequency.

        The +1s keep a term appearing in every document from scoring exactly
        zero, which would make an all-common-words question retrieve nothing at
        all rather than retrieving weakly.
        """
        return math.log((self.document_count + 1) / (self.document_frequency[token] + 1)) + 1.0

    def embed(self, text: str) -> dict[str, float]:
        """A length-normalised TF-IDF vector."""
        counts = Counter(tokenise(text))
        if not counts:
            return {}

        longest = max(counts.values())
        vector = {
            token: (0.5 + 0.5 * count / longest) * self._idf(token)
            for token, count in counts.items()
        }

        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        return {token: weight / norm for token, weight in vector.items()} if norm else {}


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    """Cosine similarity of two normalised sparse vectors.

    Iterates the smaller vector, because a question has a handful of terms and
    a chunk has hundreds.
    """
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(token, 0.0) for token, weight in left.items())


class VoyageEmbedder:
    """Hosted semantic embeddings.

    NOT COVERED BY TESTS. Running it makes real network requests against a paid
    account, so nothing in CI touches it.

    Anthropic does not serve an embeddings endpoint; Voyage is the partner
    normally paired with Claude for this. Switching to it would fix the lexical
    gap described in the README, at the cost of the offline guarantee and of
    exact eval scores — retrieval would become sampled, and every eval case
    that asserts an exact ranking would have to become a tolerance.
    """

    def __init__(self, api_key: str, model: str = "voyage-3", timeout_s: float = 20.0) -> None:
        if not api_key:
            raise ValueError(
                "VoyageEmbedder needs an API key. Leave KB_EMBEDDER unset to use "
                "the local lexical retriever."
            )
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s

    def fit(self, corpus: list[str]) -> None:  # pragma: no cover - no fitting needed
        """Hosted models need no corpus statistics."""

    def embed(self, text: str) -> dict[str, float]:  # pragma: no cover
        raise NotImplementedError(
            "Live embeddings are not implemented. Doing so means deciding how "
            "vectors are cached between runs, because re-embedding the corpus "
            "on every question is both slow and billable."
        )


def build_embedder(kind: str | None = None) -> EmbeddingProvider:
    """Return the configured embedder. Local unless told otherwise."""
    kind = (kind or os.environ.get("KB_EMBEDDER", "lexical")).strip().lower()
    if kind != "voyage":
        return LexicalEmbedder()
    return VoyageEmbedder(api_key=os.environ.get("VOYAGE_API_KEY", ""))
