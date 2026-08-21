"""Search and retrieval behind an interface.

One `Protocol`, one corpus-backed mock, one real implementation skeleton. Mock
is the default — see docs/adr/0002-mock-providers-by-default.md.
"""

from __future__ import annotations

from typing import Protocol

from agents.lead_research.fixtures import CORPUS, sources_for
from agents.lead_research.models import Source


class SearchProvider(Protocol):
    """The retrieval operations this agent needs."""

    def search(self, company: str) -> list[Source]: ...

    def fetch(self, source_id: str) -> Source | None: ...


class MockSearch:
    """Retrieval over the synthetic corpus.

    Records every query and fetch, so tests can assert the agent actually went
    and read something rather than answering from memory.
    """

    def __init__(self, corpus: dict[str, list[Source]] | None = None) -> None:
        source = corpus if corpus is not None else CORPUS
        self._corpus = {name: list(docs) for name, docs in source.items()}
        self.queries: list[str] = []
        self.fetched: list[str] = []

    def search(self, company: str) -> list[Source]:
        self.queries.append(company)
        return list(self._corpus.get(company.strip(), []))

    def fetch(self, source_id: str) -> Source | None:
        self.fetched.append(source_id)
        for documents in self._corpus.values():
            for document in documents:
                if document.id == source_id:
                    return document
        return None

    @property
    def retrieved(self) -> list[Source]:
        """Every document returned so far, for the verification pass."""
        seen: dict[str, Source] = {}
        for company in self.queries:
            for document in sources_for(company.strip()):
                seen[document.id] = document
        return list(seen.values())


class WebSearch:
    """Live web search and page retrieval.

    NOT COVERED BY TESTS. Running it would make real network requests, so
    nothing in CI touches it and it should be treated as unverified.

    Two problems are recorded here rather than glossed over. Real retrieval
    returns HTML that needs converting to text before a quote can be matched
    against it, and that conversion decides whether verification works at all.
    And real pages carry no reliable publication date, so the staleness check
    would silently stop firing — which is worse than not having it, because the
    report would still look verified.
    """

    def __init__(self, api_base_url: str, api_key: str, timeout_s: float = 15.0) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s

    def search(self, company: str) -> list[Source]:  # pragma: no cover
        raise NotImplementedError(
            "Live search is not implemented. Before it is, decide how HTML "
            "becomes quote-matchable text and where publication dates come "
            "from; verification depends on both."
        )

    def fetch(self, source_id: str) -> Source | None:  # pragma: no cover
        raise NotImplementedError("Live page retrieval is not implemented.")
