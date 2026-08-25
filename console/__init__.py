"""The operator console: workspace, chat, voice and Obsidian vault.

The layer a person actually looks at, and the only one they can type into.

An earlier version of this docstring said the console "cannot act". That is no
longer true and the correction matters: the console creates tasks, and agents
answer back through it. What remains true — and is the property everything here
is arranged around — is narrower and more useful:

    the console may create work; it has no route, button or method that
    approves any.

Nothing here sets a verdict, sends a message, books a meeting, or overrides an
escalation. Every result a task produces becomes an ordinary `Decision` and
goes through the same codex as work an agent raised on its own.
"""

from console.briefing import (
    build_notes,
    build_overlay_state,
    build_utterances,
    spoken_date,
    spoken_number,
)
from console.chat import ChatSession, RoutingDecision, supervisor_answer
from console.handlers import (
    BookingHandler,
    KnowledgeHandler,
    ResearchHandler,
    TaskHandler,
    TaskOutcome,
    find_company,
    to_decision,
)
from console.models import (
    Channel,
    OverlayCard,
    OverlayState,
    Priority,
    SpokenClip,
    Utterance,
    VaultNote,
)
from console.overlay import render_overlay
from console.server import ROUTES, build_handler, serve
from console.tasks import (
    Answer,
    Conversation,
    Question,
    Speaker,
    Task,
    TaskStatus,
    Turn,
)
from console.vault import (
    MemoryVault,
    ObsidianVault,
    VaultWriter,
    build_vault,
    render_note,
    safe_slug,
)
from console.voice import (
    BudgetExhausted,
    ElevenLabsVoice,
    MockVoice,
    VoiceProvider,
    build_voice,
)
from console.workspace import render_workspace, workspace_state

__all__ = [
    "ROUTES",
    "Answer",
    "BookingHandler",
    "BudgetExhausted",
    "Channel",
    "ChatSession",
    "Conversation",
    "ElevenLabsVoice",
    "KnowledgeHandler",
    "MemoryVault",
    "MockVoice",
    "ObsidianVault",
    "OverlayCard",
    "OverlayState",
    "Priority",
    "Question",
    "ResearchHandler",
    "RoutingDecision",
    "Speaker",
    "SpokenClip",
    "Task",
    "TaskHandler",
    "TaskOutcome",
    "TaskStatus",
    "Turn",
    "Utterance",
    "VaultNote",
    "VaultWriter",
    "VoiceProvider",
    "supervisor_answer",
    "build_handler",
    "build_notes",
    "build_overlay_state",
    "build_utterances",
    "build_vault",
    "build_voice",
    "find_company",
    "render_note",
    "render_overlay",
    "render_workspace",
    "safe_slug",
    "serve",
    "spoken_date",
    "spoken_number",
    "to_decision",
    "workspace_state",
]
