"""The operator console: overlay, voice and Obsidian vault.

The layer a person actually looks at. It observes the agent system and records
it; it cannot act on it. There is no route, button or method here that
approves, sends or books anything.
"""

from console.briefing import (
    build_notes,
    build_overlay_state,
    build_utterances,
    spoken_date,
    spoken_number,
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
from console.server import OverlayServer, build_handler, serve_forever
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

__all__ = [
    "BudgetExhausted",
    "Channel",
    "ElevenLabsVoice",
    "MemoryVault",
    "MockVoice",
    "ObsidianVault",
    "OverlayCard",
    "OverlayServer",
    "OverlayState",
    "Priority",
    "SpokenClip",
    "Utterance",
    "VaultNote",
    "VaultWriter",
    "VoiceProvider",
    "build_handler",
    "build_notes",
    "build_overlay_state",
    "build_utterances",
    "build_vault",
    "build_voice",
    "render_note",
    "render_overlay",
    "safe_slug",
    "serve_forever",
    "spoken_date",
    "spoken_number",
]
