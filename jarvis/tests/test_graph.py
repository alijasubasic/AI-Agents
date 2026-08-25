"""Tests that keep the operations sphere honest.

A systems diagram is the easiest thing in a repository to lie with. It costs
nothing to draw an arrow, nobody runs it, and a reader takes it as evidence.
So the claim at the top of `graph.py` —

    every edge in this graph corresponds to a call that exists in the code

— is asserted here against the agents' actual constructor signatures, not
against the dictionary that produced the picture. An agent that gains or loses
a provider fails this file before anyone notices the diagram drifted.
"""

from __future__ import annotations

import inspect

import pytest

from jarvis.graph import (
    AGENT_INTEGRATIONS,
    DELEGATIONS,
    INTEGRATIONS,
    Connection,
    LinkKind,
    NodeKind,
    build_graph,
    integration_status,
)
from jarvis.registry import FLEET

#: An integration node -> the constructor parameter that carries it.
#:
#: This is the bridge the drift check runs over. `calendar-booking` is drawn
#: touching Google Calendar because `CalendarBookingAgent.__init__` takes a
#: `calendar`; if that parameter is renamed or removed, the assertion below
#: fails and the picture has to be corrected with it.
PROVIDER_PARAMETERS = {
    "google-calendar": "calendar",
    "gmail": "mailbox",
    "crm": "crm",
    "web-search": "search",
}

AGENT_CLASSES = {
    "email-triage": ("agents.email_triage.agent", "EmailTriageAgent"),
    "calendar-booking": ("agents.calendar_booking.agent", "CalendarBookingAgent"),
    "lead-research": ("agents.lead_research.agent", "LeadResearchAgent"),
    "knowledge-base": ("agents.knowledge_base.agent", "KnowledgeBaseAgent"),
    "call-intake": ("agents.call_intake.agent", "CallIntakeAgent"),
}


def parameters_of(dotted: str, class_name: str) -> set[str]:
    import importlib

    module = importlib.import_module(dotted)
    return set(inspect.signature(getattr(module, class_name).__init__).parameters)


# --- The claim the whole diagram rests on --------------------------------


@pytest.mark.parametrize("agent", sorted(AGENT_CLASSES), ids=lambda name: name)
def test_every_drawn_integration_is_a_real_constructor_parameter(agent):
    """The drift check.

    Drawn edges must be backed by a provider the agent actually accepts.
    """
    drawn = set(AGENT_INTEGRATIONS.get(agent, []))
    accepted = parameters_of(*AGENT_CLASSES[agent])

    for integration in drawn:
        parameter = PROVIDER_PARAMETERS.get(integration)
        assert parameter is not None, f"{integration} has no known provider parameter"
        assert parameter in accepted, (
            f"the graph draws {agent} -> {integration}, but "
            f"{AGENT_CLASSES[agent][1]} takes no `{parameter}`"
        )


@pytest.mark.parametrize("agent", sorted(AGENT_CLASSES), ids=lambda name: name)
def test_no_provider_an_agent_takes_is_missing_from_the_diagram(agent):
    """The other direction, which is the one that rots quietly.

    An agent that gains a provider and is not added to the picture leaves the
    diagram describing a smaller system than the one that exists.
    """
    accepted = parameters_of(*AGENT_CLASSES[agent])
    drawn = set(AGENT_INTEGRATIONS.get(agent, []))

    for integration, parameter in PROVIDER_PARAMETERS.items():
        if parameter in accepted:
            assert integration in drawn, f"{agent} takes `{parameter}` but the graph omits it"


def test_every_delegation_names_agents_that_exist():
    names = {card.name for card in FLEET}
    for source, target, _label in DELEGATIONS:
        assert source in names and target in names


# --- Shape ---------------------------------------------------------------


def test_the_graph_has_one_supervisor_at_the_centre():
    graph = build_graph()
    supervisors = [node for node in graph.nodes if node.kind is NodeKind.SUPERVISOR]

    assert len(supervisors) == 1
    assert supervisors[0].ring == 0


def test_every_agent_is_reviewed_by_the_supervisor():
    """The invariant the whole architecture rests on, drawn.

    Not one agent may sit outside review. If an edge is missing here, either
    the picture is wrong or the architecture is.
    """
    graph = build_graph()
    reviewed = {link.target for link in graph.links if link.kind is LinkKind.REVIEWS}
    expected = {card.name for card in FLEET if card.name != "supervisor"}

    assert reviewed == expected


def test_no_node_is_left_without_an_edge():
    """An orphan reads as a mistake, and once was one.

    `claude-code` had no edge at all: no agent touches it, the console does.
    A node floating unconnected in a diagram that claims every edge is real
    invites the reader to assume the picture is sloppy everywhere.
    """
    graph = build_graph()
    touched = {link.source for link in graph.links} | {link.target for link in graph.links}

    orphans = sorted({node.id for node in graph.nodes} - touched)
    assert orphans == []


def test_every_link_points_at_a_node_that_exists():
    graph = build_graph()
    known = {node.id for node in graph.nodes}

    for link in graph.links:
        assert link.source in known and link.target in known


def test_integrations_declare_what_they_need():
    """A node that says "needs credentials" has to say *which*."""
    for node in INTEGRATIONS:
        if node.connection is Connection.NEEDS_CREDENTIALS:
            assert node.requires, f"{node.id} needs credentials but names none"


def test_a_local_integration_needs_no_account():
    local = {node.id for node in INTEGRATIONS if node.connection is Connection.LOCAL}
    assert local == {"obsidian", "claude-code"}


# --- Live state ----------------------------------------------------------


def test_live_task_counts_reach_the_nodes():
    graph = build_graph(tasks_by_agent={"lead-research": 3}, tone_by_agent={"lead-research": "ok"})
    node = graph.node("lead-research")

    assert node is not None
    assert (node.tasks, node.tone) == (3, "ok")


def test_connecting_google_lights_all_three_google_nodes():
    status = integration_status(google_token=True)
    graph = build_graph(connected=status)

    for name in ("google-calendar", "gmail", "google-drive"):
        node = graph.node(name)
        assert node is not None
        assert node.connection is Connection.LOCAL
        assert node.tone == "ok"


def test_nothing_configured_leaves_the_defaults_alone():
    graph = build_graph(connected=integration_status())

    calendar = graph.node("google-calendar")
    assert calendar is not None
    assert calendar.connection is Connection.NEEDS_CREDENTIALS


def test_an_override_never_upgrades_something_that_is_not_built():
    """`web-search` has no implementation, so no environment can connect it.

    The status helper only knows about the three states it can prove. Anything
    it does not name keeps the repository's own answer, which for `web-search`
    is "interface only".
    """
    graph = build_graph(connected=integration_status(google_token=True, voice_live=True))

    search = graph.node("web-search")
    assert search is not None
    assert search.connection is Connection.NOT_BUILT


def test_the_graph_serialises_for_the_page():
    payload = build_graph().model_dump(mode="json")

    assert payload["nodes"] and payload["links"]
    assert all(isinstance(node["kind"], str) for node in payload["nodes"])
    assert all(isinstance(link["kind"], str) for link in payload["links"])
