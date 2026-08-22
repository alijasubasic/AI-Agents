"""Scripted routing and supervision for the chat demo and tests.

Four requests, chosen so every path through `ChatSession` runs at least once:

* a request that routes cleanly and finishes
* a request the agent cannot start without asking — the clarification path
* a request nobody can place, which asks the operator who should take it
* a request whose answer the documents cannot support, which escalates

The routing decisions are scripted rather than computed, so the demo is
deterministic. What is *not* scripted is anything after routing: the handlers
run the real agents, the real codex reviews the results, and the real question
triage decides what reaches the operator.
"""

from __future__ import annotations

from agents.brain.models import Judgement
from console.chat import RoutingDecision
from core.llm import MockProvider, text_response

#: What the operator types, in order.
REQUESTS: list[str] = [
    "Research Kestrel Systems and tell me what we actually know about them.",
    "Have a look at that company we spoke to and pull together a profile.",
    "What restocking fee applies to opened stock?",
    "Sort out the parking situation in the office.",
]

#: One routing decision per call to the router, in the order the demo makes
#: them. The second entry is deliberate: the request names no company, so the
#: agent will have to ask — routing is not the thing that fails there.
ROUTES: list[RoutingDecision] = [
    RoutingDecision(
        agent="lead-research",
        reason="asks for what is known about a named company",
    ),
    RoutingDecision(
        agent="lead-research",
        reason="asks for a company profile, though it does not say which company",
    ),
    RoutingDecision(
        agent="knowledge-base",
        reason="a question about policy, answerable from internal documents",
    ),
    RoutingDecision(
        agent="none",
        reason="no agent here deals with facilities; this is not something I can place",
    ),
    # Re-routed after the operator names the company.
    RoutingDecision(
        agent="lead-research",
        reason="the operator named Kestrel Systems",
    ),
]


def router_provider(*, model: str = "claude-opus-5") -> MockProvider:
    """A router scripted for the whole demo."""
    return MockProvider([text_response(route.model_dump_json()) for route in ROUTES], model=model)


def brain_provider(*, count: int = 12, model: str = "claude-opus-5") -> MockProvider:
    """A reviewer that sees nothing beyond what the codex already found.

    The interesting supervision in this demo is deterministic — the codex
    articles and the question triage — so the model half is scripted flat. It
    still runs, and it still cannot loosen anything.
    """
    judgement = Judgement(
        concerns=[],
        recommend_hold=False,
        rationale="Nothing stands out beyond what the codex already covers.",
    )
    return MockProvider(
        [text_response(judgement.model_dump_json()) for _ in range(count)], model=model
    )
