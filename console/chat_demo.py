"""Runnable demonstration of the operator chat.

    python -m console.chat_demo

Four requests typed at the agents, and one answered clarification. No API key,
no network — the routing and the reviewer opinion are scripted, everything
between them is the real agents, the real codex and the real question triage.
"""

from __future__ import annotations

from agents.brain.supervisor import BrainAgent
from agents.knowledge_base.agent import KnowledgeBaseAgent
from agents.knowledge_base.fixtures import CORPUS
from agents.knowledge_base.scripted import provider_for as kb_provider
from agents.lead_research.agent import LeadResearchAgent
from agents.lead_research.fixtures import CORPUS as RESEARCH_CORPUS
from agents.lead_research.fixtures import REFERENCE_TODAY
from agents.lead_research.providers import MockSearch
from agents.lead_research.scripted import provider_for as research_provider
from console.chat import ChatSession, brain_answer
from console.handlers import KnowledgeHandler, ResearchHandler
from console.scripted import REQUESTS, brain_provider, router_provider
from console.tasks import Question, Speaker, TaskStatus
from core.config import Settings
from core.console import configure_stdout

KNOWN_COMPANIES = sorted(RESEARCH_CORPUS)

_MARK = {
    TaskStatus.DONE: "  done  ",
    TaskStatus.ESCALATED: " HUMAN  ",
    TaskStatus.BLOCKED: " BLOCK  ",
    TaskStatus.NEEDS_CLARIFICATION: " asking ",
    TaskStatus.UNROUTABLE: " asking ",
    TaskStatus.FAILED: " FAILED ",
    TaskStatus.QUEUED: " queued ",
}

_WHO = {
    Speaker.OPERATOR: "you   ",
    Speaker.AGENT: "agent ",
    Speaker.BRAIN: "brain ",
    Speaker.SYSTEM: "system",
}


class _ResearchDispatcher:
    """Builds the right scripted agent for whichever company is asked about.

    Each scripted provider answers for one company, and the chat may ask about
    any of them. Constructing the agent per call is the honest way to express
    that — the alternative is one script pretending to cover everything.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def research(self, company: str):
        return LeadResearchAgent(
            provider=research_provider(company),
            search=MockSearch(),
            settings=self._settings,
            today=REFERENCE_TODAY,
        ).research(company)


def build_session(settings: Settings | None = None) -> ChatSession:
    """Wire the chat up to real agents and a real brain."""
    settings = settings or Settings.from_env()

    research = _ResearchDispatcher(settings)
    knowledge = KnowledgeBaseAgent(
        provider=kb_provider("restocking_fee"), documents=CORPUS, settings=settings
    )

    return ChatSession(
        handlers=[
            ResearchHandler(research, KNOWN_COMPANIES),
            KnowledgeHandler(knowledge),
        ],
        router_provider=router_provider(),
        brain=BrainAgent(provider=brain_provider(), settings=settings),
        settings=settings,
    )


def run(settings: Settings | None = None) -> ChatSession:
    """Submit every fixture request, and answer the one clarification."""
    session = build_session(settings)

    for request in REQUESTS:
        task = session.submit(request)

        # Answer the company question the moment it is asked, so the demo shows
        # a clarification round-trip rather than just a stalled task.
        if task.status is TaskStatus.NEEDS_CLARIFICATION and task.open_questions:
            session.answer(task.id, task.open_questions[0].id, "Kestrel Systems")

    return session


def _print_transcript(session: ChatSession) -> None:
    print(f"\n{'=' * 78}")
    print("Transcript")
    print("=" * 78)
    for turn in session.conversation.turns:
        text = " ".join(turn.text.split())
        print(f"  {_WHO[turn.speaker]}  {text[:66]}")


def _print_tasks(session: ChatSession) -> None:
    print(f"\n{'=' * 78}")
    print("Tasks")
    print("=" * 78)
    for task in session.conversation.tasks:
        print(f"\n  [{_MARK[task.status]}] {task.request[:60]}")
        print(f"            agent:  {task.agent or '-'}  ({task.routing_reason})")
        if task.result:
            print(f"            result: {task.result[:62]}")
        for question in task.questions:
            answered = next((a.text for a in task.answers if a.question_id == question.id), None)
            state = f"answered: {answered[:40]}" if answered else "OPEN"
            print(f"            asked:  {question.text[:46]}  [{state}]")
        for reason in task.review_reasons:
            print(f"            brain:  {reason[:62]}")


def _print_triage() -> None:
    """What the brain settles without troubling the operator."""
    probes = [
        Question(
            id="p1",
            text="May I send this to the address, even though it is unconfirmed?",
            why="The caller never spelled it out.",
        ),
        Question(
            id="p2",
            text="Can I quote the 20% discount in the reply?",
            why="The customer asked for a price.",
        ),
        Question(
            id="p3",
            text="Which of the two Berlin warehouses does this order ship from?",
            why="The document names both and I cannot tell which applies.",
        ),
    ]

    print(f"\n{'=' * 78}")
    print("Question triage — what the brain answers before you see it")
    print("=" * 78)
    for question in probes:
        settled = brain_answer(question)
        if settled is None:
            print(f"\n  -> you:   {question.text}")
            print("            (no rule covers this; it needs a person)")
        else:
            _article, ruling = settled
            print(f"\n  -> brain: {question.text}")
            print(f"            {ruling[:70]}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("operator chat demo")
    print(f"mode={settings.mode}  model={settings.model}  {len(REQUESTS)} requests")

    session = run(settings)
    _print_transcript(session)
    _print_tasks(session)
    _print_triage()

    conversation = session.conversation
    waiting = conversation.waiting
    print(f"\n{'=' * 78}")
    print(
        f"{len(conversation.tasks)} tasks | {conversation.open_count} still open | "
        f"{len(waiting)} waiting on you | ${conversation.total_cost_usd:.4f}"
    )
    print(
        "\nEvery result went through the same codex as any other decision. The\n"
        "chat can create work; it has no route that approves any."
    )


if __name__ == "__main__":
    main()
