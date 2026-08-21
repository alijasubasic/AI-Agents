"""Runnable demonstration of the knowledge base agent.

    python -m agents.knowledge_base.demo

Four questions against a synthetic corpus of internal documents. One is
answered well, one thinly, one carries a citation the verifier rejects, and one
is refused before the model is ever consulted. No API key, no network.
"""

from __future__ import annotations

from agents.knowledge_base.agent import KnowledgeBaseAgent
from agents.knowledge_base.chunking import chunk_corpus
from agents.knowledge_base.fixtures import CORPUS, QUESTIONS
from agents.knowledge_base.models import Answer, Sufficiency
from agents.knowledge_base.scripted import ANSWERS, provider_for
from core.config import Settings
from core.console import configure_stdout
from core.llm import MockProvider, text_response

_MARK = {
    Sufficiency.SUFFICIENT: "  ok  ",
    Sufficiency.THIN: " THIN ",
    Sufficiency.INSUFFICIENT: "REFUSED",
}


def _agent(question_key: str, settings: Settings) -> KnowledgeBaseAgent:
    """One agent per question, so each scripted answer matches its own question.

    Questions the retriever will refuse get a provider with a response that must
    never be consumed — if the gate ever stops refusing, the leftover response
    is the evidence.
    """
    provider = (
        provider_for(question_key)
        if question_key in ANSWERS
        else MockProvider([text_response("{}")], model="claude-opus-5")
    )
    return KnowledgeBaseAgent(provider=provider, documents=CORPUS, settings=settings)


def ask_all(settings: Settings | None = None) -> list[Answer]:
    """Ask every fixture question."""
    settings = settings or Settings.from_env()
    return [_agent(key, settings).ask(question) for key, question in QUESTIONS.items()]


def _print(answer: Answer) -> None:
    retrieval = answer.retrieval
    print(f"\n{'=' * 78}")
    print(f"[{_MARK[retrieval.sufficiency]}] {answer.question}")
    print("=" * 78)
    print(f"  retrieval: {retrieval.reason}")
    for scored in retrieval.chunks[:3]:
        print(f"    {scored.score:.3f}  {scored.chunk.id:<18} {scored.chunk.preview[:44]}")

    print()
    for line in answer.text.splitlines():
        print(f"  {line}")

    if answer.good_citations:
        print("\n  verified citations:")
        for verified in answer.good_citations:
            quote = verified.citation.quote.strip()
            print(f'    ok  {verified.citation.chunk_id:<18} "{quote[:52]}..."')

    if answer.bad_citations:
        print("\n  rejected citations:")
        for verified in answer.bad_citations:
            print(
                f"    !!  {verified.citation.chunk_id:<18} {verified.status.value}: "
                f'"{verified.citation.quote.strip()[:44]}..."'
            )

    if answer.unanswered:
        print("\n  not covered:")
        for item in answer.unanswered:
            print(f"    - {item}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    chunks = chunk_corpus(CORPUS)

    print("knowledge-base demo")
    print(
        f"mode={settings.mode}  model={settings.model}  "
        f"{len(CORPUS)} documents -> {len(chunks)} chunks  retriever=lexical"
    )

    answers = ask_all(settings)
    for answer in answers:
        _print(answer)

    declined = [a for a in answers if a.declined]
    ungrounded = [a for a in answers if not a.declined and a.bad_citations]

    print(f"\n{'=' * 78}")
    print(
        f"{len(answers)} questions | {len(answers) - len(declined)} answered | "
        f"{len(declined)} refused | {len(ungrounded)} with a rejected citation"
    )
    print(
        "The refusal costs nothing: the retriever decides the corpus cannot\n"
        "support an answer, so the model is never asked the question at all."
    )


if __name__ == "__main__":
    main()
