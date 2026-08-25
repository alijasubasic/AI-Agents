"""Adapters letting a specialist agent take a free-text instruction.

Each agent in this repository has an interface shaped by its own problem —
`propose(text)`, `ask(text)`, `research(company)`. A chat gives all of them the
same thing: a sentence a person typed. These adapters bridge that, and the
bridging is where most of the honest work is.

The useful part is what happens when the bridge does not fit. `lead-research`
needs a company name; a request that does not clearly contain one cannot be
guessed at without inventing a customer. So the adapter **asks** — and that is
the whole point of `NEEDS_CLARIFICATION` existing. An adapter that guessed
would produce a confident profile of the wrong company.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, Field

from agents.supervisor.models import Decision, DecisionKind
from console.tasks import Question, Task


class TaskOutcome(BaseModel):
    """What an agent produced for one task.

    Shaped so it can become a `Decision` without the caller knowing which agent
    made it — the supervisor reviews chat-initiated work exactly as it reviews
    everything else.
    """

    summary: str = ""
    detail: str = ""

    #: Empty means the agent finished. Anything here means it is waiting.
    questions: list[Question] = Field(default_factory=list)

    #: Text that would reach someone outside the company, if any.
    outbound_text: str = ""
    recipient: str | None = None
    recipient_verified: bool | None = None
    unverified_claims: list[str] = Field(default_factory=list)

    requires_human: bool = False
    escalation_reasons: list[str] = Field(default_factory=list)

    kind: DecisionKind = DecisionKind.RECORD_CALL
    cost_usd: float = 0.0

    @property
    def needs_clarification(self) -> bool:
        return bool(self.questions)


class TaskHandler(Protocol):
    """One agent, able to take a typed instruction."""

    agent: str
    capability: str

    def handle(self, task: Task) -> TaskOutcome: ...


def to_decision(task: Task, outcome: TaskOutcome) -> Decision:
    """Turn a finished task into something the supervisor can review.

    Every field the codex inspects comes from the outcome rather than from the
    chat, so a task submitted through the overlay is indistinguishable from one
    an agent raised itself. That is the property that keeps the overlay from
    being a way around the codex.
    """
    return Decision(
        id=f"dec-task-{task.id}",
        agent=task.agent or "unknown",
        kind=outcome.kind,
        subject=task.request[:80],
        summary=outcome.summary,
        outbound_text=outcome.outbound_text,
        recipient=outcome.recipient,
        recipient_verified=outcome.recipient_verified,
        requires_human=outcome.requires_human,
        escalation_reasons=outcome.escalation_reasons,
        unverified_claims=outcome.unverified_claims,
        cost_usd=outcome.cost_usd,
        trace_ref=task.id,
    )


# --- Company extraction -------------------------------------------------


#: Companies the research agent knows about. Matching against a known list
#: rather than pulling a capitalised phrase out of the sentence: a regex would
#: happily "find" a company in "research our biggest account" and the agent
#: would then confidently profile something nobody asked about.
def find_company(text: str, known: list[str]) -> str | None:
    """The known company named in `text`, if exactly one is."""
    lowered = text.lower()
    hits = [name for name in known if name.lower() in lowered]
    return hits[0] if len(hits) == 1 else None


class ResearchHandler:
    """lead-research: profile a company from retrieved sources."""

    agent = "lead-research"
    capability = (
        "Research a company and report facts with citations. Needs to be told which company."
    )

    def __init__(self, agent_impl, known_companies: list[str]) -> None:
        self._agent = agent_impl
        self._known = known_companies

    def handle(self, task: Task) -> TaskOutcome:
        company = find_company(task.briefing, self._known)
        if company is None:
            return TaskOutcome(
                questions=[
                    Question(
                        id=f"{task.id}-company",
                        text="Which company should I research?",
                        why=(
                            "I could not identify one in the request, and "
                            "researching the wrong company produces a profile "
                            "that looks right and is about somebody else."
                        ),
                        options=self._known[:4],
                    )
                ]
            )

        result = self._agent.research(company)
        flagged = [f.fact.value for f in result.flagged]
        return TaskOutcome(
            summary=(
                f"{company}: {len(result.verified)} of {len(result.facts)} claims "
                f"verified against {len(result.sources)} source(s)."
            ),
            detail=result.profile.summary,
            unverified_claims=flagged,
            kind=DecisionKind.PUBLISH_RESEARCH,
            cost_usd=result.cost_usd,
        )


class KnowledgeHandler:
    """knowledge-base: answer from the document corpus, or decline."""

    agent = "knowledge-base"
    capability = "Answer a question from internal documents, with citations."

    def __init__(self, agent_impl) -> None:
        self._agent = agent_impl

    def handle(self, task: Task) -> TaskOutcome:
        answer = self._agent.ask(task.briefing)

        if answer.declined:
            # A refusal is a finished task, not a clarification: the documents
            # do not contain it, and no answer from the operator changes that.
            return TaskOutcome(
                summary="The documents do not cover this.",
                detail=answer.text,
                requires_human=True,
                escalation_reasons=["the corpus cannot answer this question"],
                cost_usd=answer.cost_usd,
            )

        bad = [c.citation.quote for c in answer.bad_citations]
        return TaskOutcome(
            summary=answer.text,
            detail="Sources: " + ", ".join(answer.sources) if answer.sources else "",
            unverified_claims=bad,
            requires_human=bool(bad),
            escalation_reasons=([f"{len(bad)} citation(s) failed verification"] if bad else []),
            cost_usd=answer.cost_usd,
        )


_DURATION = re.compile(r"\b(\d{1,3})\s*(?:min|minute|minuten)\b", re.IGNORECASE)


class BookingHandler:
    """calendar-booking: find times and offer them."""

    agent = "calendar-booking"
    capability = (
        "Find meeting times that work across calendars and time zones, and "
        "offer them. Needs to know who with."
    )

    def __init__(self, agent_impl, known_attendees: list[str]) -> None:
        self._agent = agent_impl
        self._known = known_attendees

    def handle(self, task: Task) -> TaskOutcome:
        proposal = self._agent.propose(task.briefing)

        if not proposal.has_options:
            return TaskOutcome(
                summary="No openings match those constraints.",
                detail=proposal.message,
                requires_human=True,
                escalation_reasons=["no mutually free time in the search window"],
            )

        return TaskOutcome(
            summary=(
                f"{len(proposal.slots)} option(s) for "
                f"{proposal.request.title!r}, {proposal.request.duration_minutes} min."
            ),
            detail="\n".join(slot.local("Europe/Berlin") for slot in proposal.slots),
            outbound_text=proposal.message,
            recipient=next(iter(proposal.request.attendee_emails), None),
            # The booking agent resolves attendees against the calendar, so an
            # address that got this far is one it recognised.
            recipient_verified=bool(proposal.request.attendee_emails),
            kind=DecisionKind.PROPOSE_TIMES,
        )
