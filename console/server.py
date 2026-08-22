"""Serving the operator console on localhost.

    python -m console.server

Four routes and no more:

    GET  /            the console
    GET  /api/state   what it renders, as JSON
    POST /api/task    give an agent something to do
    POST /api/answer  answer a question an agent asked

**This replaces an earlier read-only server, and the reason for the change is
worth stating.** That version had no POST at all, on the grounds that a console
which can act is a second path around the codex. The principle was right; the
rule was too blunt. What actually matters is that nothing reaches the outside
world unreviewed — and a task submitted here becomes an ordinary `Decision`
that the brain reviews exactly like one an agent raised itself.

So the invariant is now sharper, and still testable:

    the console may create work; it has no route that approves any.

There is no endpoint that sets a verdict, sends a message, books anything, or
overrides an escalation. `test_server.py` asserts the route table directly, so
adding one is a test failure rather than an oversight.

Two further limits, because this process can spend money:

* it binds to 127.0.0.1 and refuses to be told otherwise
* request bodies over a few kilobytes are rejected unread
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from console.chat import ChatSession
from console.models import OverlayState
from console.workspace import render_workspace, workspace_state

DEFAULT_PORT = 8756

#: Bodies are a sentence and two ids. Anything larger is a mistake or an
#: attempt, and reading it before deciding that would be the bug.
MAX_BODY_BYTES = 8 * 1024

#: The complete route table. Nothing here approves, sends, books or overrides.
ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/"): "the console",
    ("GET", "/api/state"): "current state as JSON",
    ("POST", "/api/task"): "create a task",
    ("POST", "/api/answer"): "answer an agent's question",
}

StateProvider = Callable[[], OverlayState]


def build_handler(session: ChatSession, state_provider: StateProvider):
    """A request handler bound to one chat session."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "operator-console/1.0"

        # -- helpers -----------------------------------------------------

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # The page is self-contained; nothing it needs comes from anywhere
            # else, so say so.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _state(self) -> dict:
            return workspace_state(state_provider(), session.conversation)

        def _read_json(self) -> dict | None:
            """Read a JSON body, or None if it is unusable."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length <= 0 or length > MAX_BODY_BYTES:
                return None
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return payload if isinstance(payload, dict) else None

        # -- routes ------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 - name fixed by the base class
            path = self.path.split("?", 1)[0]

            if path == "/":
                page = render_workspace(state_provider(), session.conversation)
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(self._state())
            else:
                self._json({"error": "no such route", "routes": _route_list()}, 404)

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            payload = self._read_json()

            if payload is None:
                self._json({"error": "expected a small JSON object"}, 400)
                return

            if path == "/api/task":
                request = str(payload.get("request", "")).strip()
                if not request:
                    self._json({"error": "request is empty"}, 400)
                    return
                session.submit(request)
                self._json(self._state())

            elif path == "/api/answer":
                task_id = str(payload.get("task_id", ""))
                question_id = str(payload.get("question_id", ""))
                text = str(payload.get("text", "")).strip()
                if not (task_id and question_id and text):
                    self._json({"error": "task_id, question_id and text are required"}, 400)
                    return
                if session.answer(task_id, question_id, text) is None:
                    self._json({"error": "no such task"}, 404)
                    return
                self._json(self._state())

            else:
                self._json({"error": "no such route", "routes": _route_list()}, 404)

        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(200 if self.path.split("?", 1)[0] in ("/", "/api/state") else 404)
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            """Quiet by default. The console is the interesting output."""

    return Handler


def _route_list() -> list[str]:
    return [f"{method} {path}" for method, path in sorted(ROUTES)]


def serve(
    session: ChatSession,
    state_provider: StateProvider,
    *,
    port: int = DEFAULT_PORT,
) -> None:
    """Run the console until interrupted.

    Bound to 127.0.0.1 and not configurable. This process holds an API key and
    will spend money when told to; putting it on a network interface would be a
    decision nobody should be able to make by passing an argument.
    """
    server = ThreadingHTTPServer(("127.0.0.1", port), build_handler(session, state_provider))
    print(f"Operator console on http://127.0.0.1:{port}")
    print("Routes: " + ", ".join(_route_list()))
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def main() -> None:
    from agents.brain import demo as brain_demo
    from console.briefing import build_overlay_state
    from console.chat_demo import build_session
    from core.config import Settings
    from core.console import configure_stdout

    configure_stdout()
    settings = Settings.from_env()
    report = brain_demo.run(settings)
    state = build_overlay_state(report)

    serve(build_session(settings), lambda: state)


if __name__ == "__main__":
    main()
