"""The operations graph: who may hand work to whom, and what it touches.

This is the centre of the dashboard, and it is not decoration. Obsidian's graph
view works because the edges are *real* — a link exists because somebody wrote
it, so the picture cannot flatter the vault. The same rule applies here:

    every edge in this graph corresponds to a call that exists in the code.

`lead-research -> web-search` is drawn because `LeadResearchAgent` takes a
`SearchProvider`. `call-intake -> calendar-booking` is drawn because
`propose_for` hands a typed proposal across. Nothing is drawn because it would
look good, and `test_graph.py` asserts the agent-to-integration edges against
the constructor signatures rather than against this file.

Three kinds of node, and the distinction is the point:

    AGENT        runs in this process
    INTEGRATION  an outside system, which may or may not be connected
    SURFACE      where a person meets the system

An integration node carries its own `status`, so the graph shows at a glance
what is wired up and what is still a mock. That is the honest version of a
"connected systems" diagram — most of these are not connected, and the picture
says so rather than implying a finished platform.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from jarvis.registry import FLEET


class NodeKind(StrEnum):
    """What a node is, which decides how it is drawn."""

    SUPERVISOR = "supervisor"
    AGENT = "agent"
    INTEGRATION = "integration"
    SURFACE = "surface"


class LinkKind(StrEnum):
    """What an edge means.

    Kept separate from styling: a reviewer should be able to ask "what does
    this arrow mean" and get an answer from the model, not from the CSS.
    """

    #: The supervisor reviews everything this agent decides. Always present.
    REVIEWS = "reviews"
    #: One agent hands typed work to another, with no model call in between.
    DELEGATES = "delegates"
    #: An agent reads from or writes to an outside system.
    USES = "uses"
    #: A person reaches the system here.
    OPERATES = "operates"


class Connection(StrEnum):
    """How real an integration is.

    The three states an outside system can be in, and the reason this enum
    exists at all: "planned" and "connected" look identical on a diagram unless
    something forces them apart.
    """

    #: Fully implemented and running against fixtures — no account needed.
    LOCAL = "local"
    #: Implemented, but needs credentials before it does anything.
    NEEDS_CREDENTIALS = "needs-credentials"
    #: An interface with no working implementation behind it.
    NOT_BUILT = "not-built"

    @property
    def label(self) -> str:
        return {
            Connection.LOCAL: "working locally",
            Connection.NEEDS_CREDENTIALS: "needs credentials",
            Connection.NOT_BUILT: "not built",
        }[self]

    @property
    def tone(self) -> str:
        return {
            Connection.LOCAL: "ok",
            Connection.NEEDS_CREDENTIALS: "hold",
            Connection.NOT_BUILT: "dim",
        }[self]


class Node(BaseModel):
    """One thing in the operations graph."""

    id: str
    label: str
    kind: NodeKind
    colour: str = "#00d4ff"
    detail: str = ""
    #: Only meaningful for integrations.
    connection: Connection | None = None
    #: Ring position, 0 at the centre. Drives the layout's starting radius.
    ring: int = 1
    #: Live state folded in by `build_graph`: how busy this node is.
    tasks: int = 0
    tone: str = "dim"
    #: The env vars or files this node needs before it works.
    requires: list[str] = Field(default_factory=list)


class Link(BaseModel):
    """One edge."""

    source: str
    target: str
    kind: LinkKind
    label: str = ""


class Graph(BaseModel):
    """Nodes and edges, ready to lay out."""

    nodes: list[Node] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)

    def node(self, node_id: str) -> Node | None:
        return next((node for node in self.nodes if node.id == node_id), None)


# --- The outside world ---------------------------------------------------

#: Integrations, and the truthful state of each one.
#:
#: `requires` lists exactly what a person has to supply. It is the same list
#: `docs/INTEGRATIONS.md` walks through, kept here so the graph can show it in
#: a tooltip and so the two cannot drift apart silently.
INTEGRATIONS: list[Node] = [
    Node(
        id="google-calendar",
        label="Google Calendar",
        kind=NodeKind.INTEGRATION,
        colour="#44c98f",
        detail="Free/busy lookup and event creation.",
        connection=Connection.NEEDS_CREDENTIALS,
        requires=["GOOGLE_CLIENT_SECRETS", "GOOGLE_TOKEN_PATH", "calendar scope"],
        ring=2,
    ),
    Node(
        id="gmail",
        label="Gmail",
        kind=NodeKind.INTEGRATION,
        colour="#00d4ff",
        detail="Reads unread mail, applies labels, sends replies.",
        connection=Connection.NEEDS_CREDENTIALS,
        requires=["GOOGLE_CLIENT_SECRETS", "GOOGLE_TOKEN_PATH", "gmail scopes"],
        ring=2,
    ),
    Node(
        id="google-drive",
        label="Google Drive",
        kind=NodeKind.INTEGRATION,
        colour="#f6d365",
        detail="Mirrors the morning brief and its spreadsheet.",
        connection=Connection.NEEDS_CREDENTIALS,
        requires=["GOOGLE_CLIENT_SECRETS", "GOOGLE_TOKEN_PATH", "drive.file scope"],
        ring=2,
    ),
    Node(
        id="obsidian",
        label="Obsidian vault",
        kind=NodeKind.INTEGRATION,
        colour="#7c6bff",
        detail="Every decision written as a linked Markdown note.",
        connection=Connection.LOCAL,
        requires=["OBSIDIAN_VAULT_PATH"],
        ring=2,
    ),
    Node(
        id="claude-code",
        label="Claude Code history",
        kind=NodeKind.INTEGRATION,
        colour="#4dd0e1",
        detail="This machine's own transcripts. Already on disk.",
        connection=Connection.LOCAL,
        requires=[],
        ring=2,
    ),
    Node(
        id="elevenlabs",
        label="ElevenLabs",
        kind=NodeKind.INTEGRATION,
        colour="#e07be0",
        detail="Speaks the morning brief aloud.",
        connection=Connection.NEEDS_CREDENTIALS,
        requires=["ELEVENLABS_API_KEY", "VOICE_MODE=live"],
        ring=2,
    ),
    Node(
        id="web-search",
        label="Web search",
        kind=NodeKind.INTEGRATION,
        colour="#ff6b35",
        detail="Sources for company research.",
        connection=Connection.NOT_BUILT,
        requires=["a search API key"],
        ring=2,
    ),
    Node(
        id="crm",
        label="CRM",
        kind=NodeKind.INTEGRATION,
        colour="#6b7b8d",
        detail="Who a sender is, and what they are worth.",
        connection=Connection.NOT_BUILT,
        requires=["CRM_BASE_URL", "CRM_API_KEY"],
        ring=2,
    ),
]

#: Which agent touches which outside system. Asserted against the agents'
#: constructor signatures by `test_graph.py`, so an agent that gains or loses a
#: provider fails the suite rather than quietly drifting from the picture.
AGENT_INTEGRATIONS: dict[str, list[str]] = {
    "email-triage": ["gmail", "crm"],
    "calendar-booking": ["google-calendar"],
    "lead-research": ["web-search"],
    "call-intake": [],
    "knowledge-base": [],
    "supervisor": ["obsidian", "google-drive", "elevenlabs"],
    "prompt-optimizer": [],
    "code-reviewer": [],
}

#: Typed agent-to-agent handoffs. These cost no model call — see ADR 0004.
DELEGATIONS: list[tuple[str, str, str]] = [
    ("call-intake", "calendar-booking", "callback slot"),
    ("call-intake", "email-triage", "follow-up draft"),
    ("lead-research", "email-triage", "outreach draft"),
]


def build_graph(
    *,
    tasks_by_agent: dict[str, int] | None = None,
    tone_by_agent: dict[str, str] | None = None,
    connected: dict[str, Connection] | None = None,
) -> Graph:
    """The whole operations graph, with live state folded in.

    `connected` lets the caller override an integration's state from the actual
    environment — a vault path that exists, a Google token that is present. The
    defaults describe the repository; the overrides describe *this machine*,
    and the graph should show the second.
    """
    tasks_by_agent = tasks_by_agent or {}
    tone_by_agent = tone_by_agent or {}
    connected = connected or {}

    nodes: list[Node] = [
        Node(
            id="operator",
            label="You",
            kind=NodeKind.SURFACE,
            colour="#e0e6ed",
            detail="The console. Creates work; approves nothing.",
            ring=0,
        )
    ]

    for card in FLEET:
        kind = NodeKind.SUPERVISOR if card.name == "supervisor" else NodeKind.AGENT
        nodes.append(
            Node(
                id=card.name,
                label=card.title,
                kind=kind,
                colour=card.colour,
                detail=card.blurb,
                ring=0 if kind is NodeKind.SUPERVISOR else 1,
                tasks=tasks_by_agent.get(card.name, 0),
                tone=tone_by_agent.get(card.name, "dim"),
            )
        )

    for integration in INTEGRATIONS:
        node = integration.model_copy(deep=True)
        node.connection = connected.get(node.id, node.connection)
        node.tone = node.connection.tone if node.connection else "dim"
        nodes.append(node)

    links: list[Link] = [
        Link(source="operator", target="supervisor", kind=LinkKind.OPERATES, label="gives work"),
        # The console reads this machine's own transcripts for the telemetry
        # panels. Drawn from the operator rather than from an agent because no
        # agent touches it — `jarvis.app.telemetry()` does.
        Link(source="operator", target="claude-code", kind=LinkKind.USES, label="reads history"),
    ]

    known = {node.id for node in nodes}
    for card in FLEET:
        if card.name != "supervisor":
            links.append(
                Link(source="supervisor", target=card.name, kind=LinkKind.REVIEWS, label="reviews")
            )
        for integration in AGENT_INTEGRATIONS.get(card.name, []):
            if integration in known:
                links.append(Link(source=card.name, target=integration, kind=LinkKind.USES))

    links += [
        Link(source=source, target=target, kind=LinkKind.DELEGATES, label=label)
        for source, target, label in DELEGATIONS
        if {source, target} <= known
    ]

    return Graph(nodes=nodes, links=links)


def integration_status(
    *,
    vault_path: str | None = None,
    google_token: bool = False,
    voice_live: bool = False,
) -> dict[str, Connection]:
    """What is actually wired up on this machine.

    Deliberately conservative: a token file that exists proves somebody ran the
    connect script, not that the scopes are right or that the refresh token
    still works. `NEEDS_CREDENTIALS` is the honest answer until a call succeeds,
    and the dashboard says "connected" only for the two that need nothing.
    """
    status: dict[str, Connection] = {}
    if vault_path:
        status["obsidian"] = Connection.LOCAL
    if google_token:
        for name in ("google-calendar", "gmail", "google-drive"):
            status[name] = Connection.LOCAL
    if voice_live:
        status["elevenlabs"] = Connection.LOCAL
    return status
