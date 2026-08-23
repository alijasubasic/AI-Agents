"""The agent fleet, as data.

The dashboard this is modelled on keeps its fleet in a Markdown file with a
YAML header that a person edits by hand. That is the right shape — a fleet is
data, and hard-coding cards is how a dashboard ends up describing agents that
were deleted a year ago.

**The change made here is that the data is checked against reality.** A
hand-maintained registry drifts the moment somebody renames a module, and it
drifts silently, which is the worst way. So every entry names the package it
describes, and `test_registry.py` asserts that the package exists, that the
entry point is importable, that the README is there, and — the one that
actually catches drift — that no agent package is *missing* from this list.

Add an agent to `agents/` without adding it here and the suite fails.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

#: Where the agent packages live, relative to the repository root.
AGENTS_DIR = Path("agents")


class AgentCard(BaseModel):
    """One agent, as the fleet panel shows it."""

    #: Hyphenated public name. Matches the chat router's vocabulary where the
    #: agent is reachable from the console at all.
    name: str
    title: str
    #: Python package under `agents/`.
    package: str
    #: Accent colour. Chosen per agent so a card is recognisable at a glance
    #: before you have read the name.
    colour: str
    blurb: str
    #: What it can be asked to do, in the operator's words. Short enough to fit
    #: as pills under the title.
    skills: list[str] = Field(default_factory=list)
    #: True when the console's chat can hand it a free-text request. The rest
    #: run on structured fixtures and have nothing sensible to take from a
    #: chat box, which the panel says rather than hides.
    reachable: bool = False
    #: The module `python -m` runs for this agent's demonstration.
    demo: str = ""

    @property
    def initials(self) -> str:
        """Two letters for the avatar, derived rather than stored."""
        parts = [part for part in self.name.replace("_", "-").split("-") if part]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return self.name[:2].upper()

    @property
    def readme(self) -> Path:
        return AGENTS_DIR / self.package / "README.md"


#: The fleet. Ordered as the dashboard shows it: the supervisor first, because
#: everything else answers to it, then the working agents, then the two that
#: operate on the repository itself.
FLEET: list[AgentCard] = [
    AgentCard(
        name="brain",
        title="Brain",
        package="brain",
        colour="#7c6bff",
        blurb=(
            "Supervises every other agent. Re-checks each decision against an "
            "eight-article codex and writes the morning brief."
        ),
        skills=["supervision", "codex", "morning brief"],
        demo="agents.brain.demo",
    ),
    AgentCard(
        name="email-triage",
        title="Email Triage",
        package="email_triage",
        colour="#00d4ff",
        blurb=(
            "Classifies inbound business email, extracts action items and "
            "drafts a reply in a house voice."
        ),
        skills=["classify", "extract", "draft"],
        demo="agents.email_triage.demo",
    ),
    AgentCard(
        name="calendar-booking",
        title="Calendar Booking",
        package="calendar_booking",
        colour="#44c98f",
        blurb=(
            "Finds times that work across several calendars and time zones, "
            "and respects working hours rather than averaging them."
        ),
        skills=["availability", "time zones", "proposals"],
        reachable=True,
        demo="agents.calendar_booking.demo",
    ),
    AgentCard(
        name="call-intake",
        title="Call Intake",
        package="call_intake",
        colour="#ff6b35",
        blurb=(
            "Turns a call transcript into a verified, routed record — and "
            "treats the transcript as data, never as instructions."
        ),
        skills=["transcribe", "verify quotes", "route"],
        demo="agents.call_intake.demo",
    ),
    AgentCard(
        name="lead-research",
        title="Lead Research",
        package="lead_research",
        colour="#f6d365",
        blurb=(
            "Researches a company, extracts structured facts with citations, "
            "and labels every claim it could not source."
        ),
        skills=["search", "cite", "flag unverified"],
        reachable=True,
        demo="agents.lead_research.demo",
    ),
    AgentCard(
        name="knowledge-base",
        title="Knowledge Base",
        package="knowledge_base",
        colour="#4dd0e1",
        blurb=(
            "Answers from a document corpus with a citation for every claim, "
            "and declines when retrieval brings back nothing separable."
        ),
        skills=["retrieve", "quote", "refuse"],
        reachable=True,
        demo="agents.knowledge_base.demo",
    ),
    AgentCard(
        name="self-improving",
        title="Self-Improving",
        package="self_improving",
        colour="#e07be0",
        blurb=(
            "An evaluator-optimizer loop: a critic reads what a prompt got "
            "wrong, an optimiser rewrites it, a holdout set keeps it honest."
        ),
        skills=["critique", "rewrite", "holdout"],
        demo="agents.self_improving.demo",
    ),
    AgentCard(
        name="improver",
        title="Improver",
        package="improver",
        colour="#e05561",
        blurb=(
            "Reviews this repository and proposes patches it cannot merge — "
            "tests, evals and CI config are outside what it may touch."
        ),
        skills=["review", "patch", "verify"],
        demo="agents.improver.demo",
    ),
]

BY_NAME: dict[str, AgentCard] = {card.name: card for card in FLEET}


def reachable_names() -> list[str]:
    """The agents the console chat can actually hand a sentence to."""
    return [card.name for card in FLEET if card.reachable]


def packages_on_disk(root: Path | None = None) -> set[str]:
    """Every agent package that actually exists.

    The other half of the drift check: comparing this against `FLEET` is what
    turns the registry from documentation into something that can be wrong.
    """
    directory = (root or Path()) / AGENTS_DIR
    try:
        entries = list(directory.iterdir())
    except OSError:
        return set()
    return {
        entry.name
        for entry in entries
        if entry.is_dir()
        and not entry.name.startswith(("_", "."))
        and (entry / "__init__.py").exists()
    }
