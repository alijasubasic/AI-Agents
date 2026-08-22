"""The operator console, end to end.

    python -m console.demo

Runs the whole agent system, renders the overlay, speaks the briefing through
the voice provider, and records everything into an Obsidian vault.

Mock voice and a local vault by default, so this works on a clone with no API
key, no ElevenLabs account and no vault of your own. Point it at real ones with
two environment variables — see this package's README.
"""

from __future__ import annotations

import os
from pathlib import Path

from agents.brain import demo as brain_demo
from agents.brain.models import DailyReport, Verdict
from console.briefing import build_notes, build_overlay_state, build_utterances
from console.models import SpokenClip
from console.overlay import render_overlay
from console.vault import ObsidianVault, build_vault
from console.voice import BudgetExhausted, MockVoice, VoiceProvider
from core.config import Settings
from core.console import configure_stdout

OVERLAY_PATH = Path("briefs/overlay.html")

#: Where notes land when OBSIDIAN_VAULT_PATH is not set. Git-ignored, so a
#: clone can run this without writing into anybody's real notes.
DEFAULT_VAULT_PATH = Path("vault")


def speak_briefing(report: DailyReport, voice: VoiceProvider) -> list[SpokenClip]:
    """Read the briefing aloud.

    Nothing that was blocked is ever spoken as though it happened. The briefing
    is built from the report's own verdicts, and a blocked decision is
    announced as blocked or not at all — there is no path where the voice
    reports something as done that the codex refused.
    """
    clips: list[SpokenClip] = []
    for utterance in build_utterances(report):
        if not utterance.to_speak:
            continue
        try:
            clips.append(voice.speak(utterance))
        except BudgetExhausted as exc:
            # Running out of characters stops the speaking, not the briefing.
            clips.append(
                SpokenClip(
                    utterance_id=utterance.id,
                    text=utterance.to_speak,
                    error=str(exc),
                )
            )
            break
    return clips


def record_to_vault(report: DailyReport, vault: ObsidianVault) -> list[str]:
    """Write every decision, codex article and the brief itself into the vault."""
    return [vault.write(note) for note in build_notes(report)]


def resolve_vault_path(explicit: Path | str | None = None) -> Path:
    """Where notes should go: an explicit path, then the environment, then local.

    Resolved in one place and passed down as an argument rather than read from
    the environment deep inside `run`. That difference matters: with the
    environment consulted at the bottom, a test that forgot to clear
    `OBSIDIAN_VAULT_PATH` would write into somebody's real notes, and it would
    do so silently.
    """
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get("OBSIDIAN_VAULT_PATH") or DEFAULT_VAULT_PATH)


def run(
    settings: Settings | None = None, *, vault_path: Path | str | None = None
) -> tuple[DailyReport, MockVoice, ObsidianVault]:
    """Run everything and return what each layer produced."""
    settings = settings or Settings.from_env()
    report = brain_demo.run(settings)

    voice = MockVoice()
    speak_briefing(report, voice)

    vault = build_vault(resolve_vault_path(vault_path))
    record_to_vault(report, vault)

    return report, voice, vault


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("console demo - overlay, voice and vault")
    vault_path = resolve_vault_path()
    print(f"mode={settings.mode}  voice=mock  vault={vault_path}")

    report = brain_demo.run(settings)
    state = build_overlay_state(report)

    # --- Overlay --------------------------------------------------------
    OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERLAY_PATH.write_text(render_overlay(state), encoding="utf-8")

    print(f"\n{'=' * 76}")
    print(f"Overlay   {OVERLAY_PATH}  ({OVERLAY_PATH.stat().st_size:,} bytes, self-contained)")
    print(f"          {state.approved} approved | {state.held} held | {state.blocked} blocked")

    # --- Voice ----------------------------------------------------------
    voice = MockVoice()
    clips = speak_briefing(report, voice)
    spoken_characters = sum(clip.characters for clip in clips)

    print(
        f"\nVoice     {len(clips)} clips, {spoken_characters:,} characters "
        f"({voice.remaining:,} left in budget)"
    )
    for clip in clips[:3]:
        print(f'          "{clip.text[:66]}{"..." if len(clip.text) > 66 else ""}"')
    if len(clips) > 3:
        print(f"          ... and {len(clips) - 3} more")

    # --- Vault ----------------------------------------------------------
    vault = build_vault(vault_path)
    written = record_to_vault(report, vault)
    folders: dict[str, int] = {}
    for path in written:
        folder = Path(path).parent.name
        folders[folder] = folders.get(folder, 0) + 1

    print(f"\nVault     {len(written)} notes into {vault_path}")
    for folder, count in sorted(folders.items()):
        print(f"          {folder}/  {count} notes")

    blocked = [r for r in report.reviews if r.verdict is Verdict.BLOCKED]
    print(f"\n{'=' * 76}")
    print(
        f"The {len(blocked)} blocked decisions are recorded as blocked in all three "
        f"places.\nNothing the codex refused is spoken or displayed as though it "
        f"happened.\n\n"
        f"Open the overlay:   {OVERLAY_PATH}\n"
        f"Live version:       python -m console.server\n"
        f"Vault in Obsidian:  open {vault_path} as a vault, then look at the\n"
        f"                    backlinks on any note in Codex/"
    )


if __name__ == "__main__":
    main()
