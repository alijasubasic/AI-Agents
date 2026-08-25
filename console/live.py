"""Building a console session that can be used, rather than demonstrated.

`chat_demo.build_session` wires everything to scripted providers: five routing
decisions, one answer per question. That is right for a demo and wrong for a
console somebody types into — the sixth request exhausts the script and the
task fails with a provider error.

This builds the same session against the real API instead. The distinction
worth being precise about:

    live mode makes the *reasoning* real. It does not make the *data* real.

The calendar is still `MockCalendar`, the research corpus is still fixtures,
and the knowledge base still answers from the four synthetic documents in
`agents/knowledge_base/fixtures.py`. Those are the integrations nobody has
built — `GoogleCalendar`, `WebSearch` and the rest raise `NotImplementedError`
by design. What changes here is that a real model does the routing, the
answering and the supervising.
"""

from __future__ import annotations

from agents.calendar_booking.agent import CalendarBookingAgent
from agents.calendar_booking.fixtures import ORGANISER, PEOPLE
from agents.calendar_booking.providers import MockCalendar
from agents.knowledge_base.agent import KnowledgeBaseAgent
from agents.knowledge_base.fixtures import CORPUS as DOCUMENTS
from agents.lead_research.fixtures import CORPUS as RESEARCH_CORPUS
from agents.lead_research.fixtures import REFERENCE_TODAY
from agents.lead_research.providers import MockSearch
from agents.supervisor.agent import SupervisorAgent
from console.chat import ChatSession
from console.handlers import BookingHandler, KnowledgeHandler, ResearchHandler
from core.config import Settings
from core.llm import AnthropicProvider

KNOWN_COMPANIES = sorted(RESEARCH_CORPUS)
KNOWN_ATTENDEES = sorted(PEOPLE)


class LiveResearch:
    """Research any company in the corpus with a real model behind it.

    Constructed per request rather than once: the research agent holds its own
    conversation, and reusing one across unrelated companies would carry the
    previous profile into the next answer.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def research(self, company: str):
        from agents.lead_research.agent import LeadResearchAgent

        return LeadResearchAgent(
            provider=AnthropicProvider(self._settings),
            search=MockSearch(),
            settings=self._settings,
            today=REFERENCE_TODAY,
        ).research(company)


def build_live_session(settings: Settings | None = None) -> ChatSession:
    """A console session backed by the real API.

    Raises if the settings are not live, rather than quietly falling back to
    mocks — a console that silently answered from scripts would be worse than
    one that refused to start.
    """
    settings = settings or Settings.from_env()
    if not settings.is_live:
        raise RuntimeError(
            "build_live_session needs AGENT_MODE=live and an ANTHROPIC_API_KEY. "
            "Use console.chat_demo.build_session for the scripted demo."
        )

    knowledge = KnowledgeBaseAgent(
        provider=AnthropicProvider(settings), documents=DOCUMENTS, settings=settings
    )
    booking = CalendarBookingAgent(
        provider=AnthropicProvider(settings),
        calendar=MockCalendar(),
        organiser=ORGANISER,
        settings=settings,
    )

    return ChatSession(
        handlers=[
            ResearchHandler(LiveResearch(settings), KNOWN_COMPANIES),
            KnowledgeHandler(knowledge),
            BookingHandler(booking, KNOWN_ATTENDEES),
        ],
        router_provider=AnthropicProvider(settings),
        supervisor=SupervisorAgent(provider=AnthropicProvider(settings), settings=settings),
        settings=settings,
    )


def build_session_for(settings: Settings | None = None) -> tuple[ChatSession, bool]:
    """The right session for the configured mode, and whether it is live.

    Returning the flag rather than hiding it: the console prints which one it
    got, because "why is it answering the same thing every time" has exactly
    one cause and it should not take anybody ten minutes to find.
    """
    settings = settings or Settings.from_env()
    if settings.is_live:
        return build_live_session(settings), True

    from console.chat_demo import build_session

    return build_session(settings), False
