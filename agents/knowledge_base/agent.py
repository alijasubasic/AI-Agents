"""The knowledge base agent.

    retrieve  →  assess  →  (answer | decline)  →  verify citations

The second step is the one that matters. `assess` is deterministic code, it
runs before the model is consulted, and it can refuse outright. For a question
the corpus cannot answer, the agent returns "I don't know" **without spending a
token** — the model never sees the question, so it never gets the chance to
write a confident answer from three irrelevant paragraphs.

The fourth step is the same idea as `lead-research`, one level down: every
sentence cites a chunk, and every citation is checked against the chunk it
names.
"""

from __future__ import annotations

import re
import time

from agents.knowledge_base.chunking import chunk_corpus
from agents.knowledge_base.embedding import EmbeddingProvider
from agents.knowledge_base.models import (
    Answer,
    Chunk,
    CitationStatus,
    Document,
    DraftAnswer,
    Retrieval,
    Sufficiency,
    VerifiedCitation,
)
from agents.knowledge_base.retrieval import DEFAULT_TOP_K, VectorIndex, retrieve
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider

SYSTEM_PROMPT = """\
You answer questions about a company's internal documents.

You will be given the question and a numbered set of retrieved passages. Answer
from those passages and nothing else.

Rules:

- Every sentence of your answer cites the passage it came from, with the exact
  span from that passage that supports it. The span is checked against the
  passage, so copy it rather than paraphrasing it.
- Use only the passages given. You have no other knowledge of this company, and
  anything you add from elsewhere will be wrong for this customer even when it
  is true in general.
- If the passages answer part of the question and not the rest, answer the part
  they cover and put the rest in `unanswered`. Naming a gap is more useful than
  filling it.
- Do not soften a limit or a fee to sound more helpful. "14 days" is not "about
  two weeks" when a customer is deciding whether to post something today.
"""

QUESTION_TEMPLATE = """\
Question: {question}

Retrieved passages:

{passages}
"""

DECLINE_TEMPLATE = (
    "I do not have enough in the documents to answer that. {reason}.\n\n"
    "Nothing retrieved covers: {uncovered}."
)

_SPACE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _SPACE.sub(" ", text).strip().lower()


def render_passages(retrieval: Retrieval) -> str:
    """The retrieved chunks, as the model sees them."""
    return "\n\n".join(
        f"[{scored.chunk.id}] from {scored.chunk.document_title} "
        f"(similarity {scored.score:.2f})\n---\n{scored.chunk.text}"
        for scored in retrieval.chunks
    )


def verify_citations(draft: DraftAnswer, retrieval: Retrieval) -> list[VerifiedCitation]:
    """Check every citation against the chunk it names.

    Two ways to fail, kept apart because they mean different things. Citing a
    chunk that was never retrieved means the model invented an id; citing a
    real chunk that does not contain the quote means it invented the support.
    """
    by_id: dict[str, Chunk] = {scored.chunk.id: scored.chunk for scored in retrieval.chunks}
    verified: list[VerifiedCitation] = []

    for citation in draft.citations:
        chunk = by_id.get(citation.chunk_id)
        if chunk is None:
            verified.append(VerifiedCitation(citation=citation, status=CitationStatus.UNRETRIEVED))
        elif _normalise(citation.quote) and _normalise(citation.quote) in _normalise(chunk.text):
            verified.append(
                VerifiedCitation(citation=citation, status=CitationStatus.VERIFIED, chunk=chunk)
            )
        else:
            verified.append(
                VerifiedCitation(citation=citation, status=CitationStatus.UNSUPPORTED, chunk=chunk)
            )

    return verified


class KnowledgeBaseAgent:
    """Answers questions from a document corpus, or declines to."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        documents: list[Document],
        embedder: EmbeddingProvider | None = None,
        settings: Settings | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self.index = VectorIndex(embedder).index(chunk_corpus(documents))
        self.top_k = top_k
        self._agent = Agent(
            name="knowledge-base",
            system_prompt=SYSTEM_PROMPT,
            provider=provider,
            settings=settings,
        )

    def ask(self, question: str) -> Answer:
        """Answer a question, or say honestly that the corpus cannot."""
        started = time.monotonic()
        retrieval = retrieve(self.index, question, top_k=self.top_k)

        if not retrieval.may_answer:
            return Answer(
                question=question,
                retrieval=retrieval,
                text=self._decline(retrieval),
                declined=True,
                duration_ms=(time.monotonic() - started) * 1000,
            )

        draft, run = self._agent.run_structured(
            QUESTION_TEMPLATE.format(question=question, passages=render_passages(retrieval)),
            DraftAnswer,
        )

        citations = verify_citations(draft, retrieval)
        unanswered = list(draft.unanswered)
        if retrieval.sufficiency is Sufficiency.THIN and retrieval.uncovered_terms:
            unanswered.append(
                "The documents only weakly cover: " + ", ".join(retrieval.uncovered_terms[:4])
            )

        return Answer(
            question=question,
            retrieval=retrieval,
            text=draft.answer,
            citations=citations,
            unanswered=unanswered,
            declined=False,
            cost_usd=run.cost_usd,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    # -- internals -------------------------------------------------------

    def _decline(self, retrieval: Retrieval) -> str:
        """Say no, and say why. Rendered, not generated.

        A declined answer is the one place a model would be most tempted to be
        helpful, so no model is involved in writing it.
        """
        uncovered = ", ".join(retrieval.uncovered_terms[:5]) or "the question as asked"
        return DECLINE_TEMPLATE.format(reason=retrieval.reason, uncovered=uncovered)


def render_answer(answer: Answer) -> str:
    """The answer as Markdown, with its citations. No model call."""
    lines = [f"**Q:** {answer.question}", ""]

    if answer.declined:
        lines += [answer.text, "", f"_Retrieval: {answer.retrieval.sufficiency.value}._"]
        return "\n".join(lines)

    lines += [answer.text, ""]

    if answer.good_citations:
        lines += ["## Sources", ""]
        for verified in answer.good_citations:
            chunk = verified.chunk
            lines.append(
                f"- **{chunk.document_title}** (`{chunk.id}`) — “{verified.citation.quote.strip()}”"
            )
        lines.append("")

    if answer.bad_citations:
        lines += ["## Unverified citations", ""]
        lines += [
            f"- `{verified.citation.chunk_id}` — {verified.status.value}: "
            f"“{verified.citation.quote.strip()[:80]}”"
            for verified in answer.bad_citations
        ]
        lines.append("")

    if answer.unanswered:
        lines += ["## Not covered by the documents", ""]
        lines += [f"- {item}" for item in answer.unanswered]

    return "\n".join(lines).strip()
