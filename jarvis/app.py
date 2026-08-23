"""Wiring the dashboard to the console server.

    python -m jarvis            # http://127.0.0.1:8756

This is the only module that knows about all of the pieces at once — the chat
session, the morning brief, telemetry, diagnostics and the vault. Everything
else stays ignorant of the others, which is why they are testable apart.

Two decisions about *when* work happens, both visible on screen:

* **Diagnostics are measured once, at startup.** Running the eval suite takes a
  couple of seconds. On a four-second poll that would mean the machine never
  stops working, to redraw six numbers that change when the code changes.
* **Telemetry is re-read on every request.** It is cached against file
  modification times, so a refresh costs a `stat` per transcript — cheap enough
  to keep the live-session panel actually live.
"""

from __future__ import annotations

import os
from pathlib import Path

from console.chat import ChatSession
from console.live import build_session_for
from console.models import OverlayState
from console.server import DEFAULT_PORT, serve
from core.config import Settings
from core.console import configure_stdout
from jarvis import capture as capture_module
from jarvis.diagnostics import Diagnostics, measure
from jarvis.page import render_dashboard
from jarvis.panels import Dashboard, build
from telemetry import load
from telemetry.models import Telemetry


class App:
    """Everything the server needs, assembled once.

    Holds the pieces rather than rebuilding them per request: the chat session
    carries the conversation, and constructing a new one on each poll would
    lose it.
    """

    def __init__(
        self,
        *,
        session: ChatSession,
        overlay: OverlayState,
        diagnostics: Diagnostics,
        settings: Settings,
        vault_path: Path | str | None = None,
        telemetry_root: Path | None = None,
    ) -> None:
        self.session = session
        self.overlay = overlay
        self.diagnostics = diagnostics
        self.settings = settings
        self.telemetry_root = telemetry_root
        self.vault_path = Path(vault_path) if vault_path else None

    # -- data ------------------------------------------------------------

    def telemetry(self) -> Telemetry:
        return load(self.telemetry_root)

    def dashboard(self) -> Dashboard:
        return build(
            state=self.overlay,
            conversation=self.session.conversation,
            telemetry=self.telemetry(),
            diagnostics=self.diagnostics,
            mode=self.settings.mode,
            model=self.settings.model,
            capture_target=str(self.vault_path) if self.vault_path else "",
        )

    def payload(self) -> dict:
        return self.dashboard().model_dump(mode="json")

    def page(self) -> str:
        return render_dashboard(self.dashboard())

    # -- the one route that writes ---------------------------------------

    def capture(self, title: str, body: str) -> str:
        """Write a note. Raises `CaptureRefused` on anything unacceptable.

        The vault writer is built per call rather than held open, so a vault
        that appears — or moves — while the server is running is picked up
        without a restart.
        """
        if self.vault_path is None:
            raise capture_module.CaptureRefused("no vault configured")
        from console.vault import build_vault

        return capture_module.capture(build_vault(self.vault_path), title, body)


def resolve_vault(explicit: Path | str | None = None) -> Path:
    """Where captures go.

    Read once, here, and passed down — not looked up deep inside a write. That
    ordering is deliberate: an earlier version of the console read the
    environment variable at the moment it wrote, which meant a demo could write
    into somebody's real vault depending on how it was launched.
    """
    if explicit:
        return Path(explicit)
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(configured) if configured else Path("vault")


def build_app(
    settings: Settings | None = None,
    *,
    run_evals: bool = True,
    vault_path: Path | str | None = None,
    telemetry_root: Path | None = None,
) -> tuple[App, bool]:
    """The application and whether it got a live session."""
    from agents.brain import demo as brain_demo
    from console.briefing import build_overlay_state

    settings = settings or Settings.from_env()
    session, is_live = build_session_for(settings)

    # The morning brief always comes from the scripted run. It is yesterday's
    # record; regenerating it against the live API on every start would cost
    # money to redraw a panel that is not about today.
    overlay = build_overlay_state(brain_demo.run(settings.model_copy(update={"mode": "mock"})))

    app = App(
        session=session,
        overlay=overlay,
        diagnostics=measure(settings, run_evals=run_evals),
        settings=settings,
        vault_path=resolve_vault(vault_path),
        telemetry_root=telemetry_root,
    )
    return app, is_live


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()

    print("Starting J.A.R.V.I.S. — running the eval suite once, a moment…")
    app, is_live = build_app(settings)

    telemetry = app.telemetry()
    print()
    if is_live:
        print(f"  reasoning:  live on {settings.model} — each request costs a few cents")
        print("  data:       fixtures. No real calendar, mailbox or web search.")
    else:
        print("  reasoning:  scripted. Set AGENT_MODE=live with an ANTHROPIC_API_KEY")
        print("              for a console you can actually work in.")
    source = telemetry.source if telemetry.real else "fixtures — no history found"
    print(f"  telemetry:  {source}")
    print(f"  captures:   {app.vault_path}")
    print()

    serve(
        app.session,
        lambda: app.overlay,
        port=DEFAULT_PORT,
        dashboard_provider=app.payload,
        dashboard_page=app.page,
        capture_writer=app.capture,
    )


if __name__ == "__main__":
    main()
