"""Data models for the operator console.

The console is the layer a person actually looks at: an overlay showing what
the agents did, a voice reading it out, and an Obsidian vault recording it.

One rule shapes every model here: **the console observes, it never acts.**
Nothing in this package can approve a decision, send an email, or book a
meeting. A heads-up display with action buttons would be a second path around
the codex, and an un-audited one, which is exactly what the rest of this
repository is built to avoid.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from agents.supervisor.models import Verdict


class Channel(StrEnum):
    """Where a line of the briefing is meant to land."""

    SPOKEN = "spoken"
    DISPLAY = "display"
    BOTH = "both"


class Priority(StrEnum):
    """How loudly the overlay should present something."""

    ALERT = "alert"
    ATTENTION = "attention"
    ROUTINE = "routine"


class Utterance(BaseModel):
    """One line of the briefing, ready to be shown or spoken.

    Kept separate from the text that goes on screen: a number reads badly out
    loud ("2 of 7" versus "two out of seven"), and an abbreviation that is fine
    in a table is unintelligible in speech.
    """

    id: str
    display_text: str
    spoken_text: str = ""
    channel: Channel = Channel.BOTH
    priority: Priority = Priority.ROUTINE
    source_decision: str | None = None

    @property
    def to_speak(self) -> str:
        """What the voice provider receives. Empty when this is display-only."""
        if self.channel is Channel.DISPLAY:
            return ""
        return self.spoken_text or self.display_text


class SpokenClip(BaseModel):
    """The result of asking a voice provider to say something."""

    utterance_id: str
    text: str
    audio_bytes: int = 0
    characters: int = 0
    voice_id: str = ""
    path: str | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class VaultNote(BaseModel):
    """One Markdown note written into an Obsidian vault."""

    #: Filename stem. Stable across runs so re-running updates rather than
    #: duplicating.
    slug: str
    folder: str
    title: str
    frontmatter: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    body: str = ""
    links: list[str] = Field(default_factory=list)

    @property
    def path_parts(self) -> tuple[str, str]:
        return self.folder, f"{self.slug}.md"


class OverlayCard(BaseModel):
    """One decision as the overlay shows it."""

    decision_id: str
    agent: str
    subject: str
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    recipient: str | None = None

    @property
    def tone(self) -> str:
        """CSS class name for this card's verdict."""
        return {
            Verdict.APPROVED: "ok",
            Verdict.HOLD_FOR_HUMAN: "hold",
            Verdict.BLOCKED: "block",
        }[self.verdict]


class OverlayState(BaseModel):
    """Everything the overlay renders. A snapshot, never a control surface."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    heading: str = ""
    subheading: str = ""

    approved: int = 0
    held: int = 0
    blocked: int = 0
    autonomy_rate: float = 0.0
    cost_usd: float = 0.0

    cards: list[OverlayCard] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    utterances: list[Utterance] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return self.approved + self.held + self.blocked

    @property
    def needs_attention(self) -> int:
        return self.held + self.blocked
