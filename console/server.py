"""A local, read-only server for the overlay.

    python -m console.server

Two routes and nothing else:

    GET /            the HUD
    GET /api/state   the current snapshot as JSON

**There is no third route.** No POST, no PUT, no DELETE — the handler refuses
every method except GET and HEAD before it looks at the path. That is not
tidiness; it is the same argument as codex article A1. A display that can also
act is a second way to approve something, and one that never passes through the
codex or lands in the audit trail.

`http.server` from the standard library is not a production web server, and
this is not a production web service. It binds to localhost, serves one person,
and holds no state of its own.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from console.models import OverlayState
from console.overlay import render_overlay

#: Localhost only. Binding to 0.0.0.0 would put an unauthenticated view of the
#: company's decisions on the local network.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

StateProvider = Callable[[], OverlayState]


def build_handler(state_provider: StateProvider) -> type[BaseHTTPRequestHandler]:
    """Build a request handler serving whatever `state_provider` returns."""

    class OverlayHandler(BaseHTTPRequestHandler):
        server_version = "AgentOverlay/1.0"

        # -- the only two things this server does ------------------------

        def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
            path = self.path.split("?", 1)[0].rstrip("/") or "/"

            if path == "/":
                body = render_overlay(state_provider(), endpoint="/api/state").encode("utf-8")
                self._respond(HTTPStatus.OK, "text/html; charset=utf-8", body)
            elif path == "/api/state":
                body = state_provider().model_dump_json().encode("utf-8")
                self._respond(HTTPStatus.OK, "application/json; charset=utf-8", body)
            else:
                self._respond(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        # -- everything else is refused ----------------------------------

        def _refuse(self) -> None:
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_POST = _refuse  # noqa: N815
        do_PUT = _refuse  # noqa: N815
        do_PATCH = _refuse  # noqa: N815
        do_DELETE = _refuse  # noqa: N815

        # -- plumbing ----------------------------------------------------

        def _respond(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            """Silence per-request logging; the overlay polls every few seconds."""

    return OverlayHandler


class OverlayServer:
    """A running overlay server. Usable as a context manager in tests."""

    def __init__(
        self,
        state_provider: StateProvider,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._httpd = ThreadingHTTPServer((host, port), build_handler(state_provider))
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[0], self.port
        return f"http://{host}:{port}/"

    def start(self) -> OverlayServer:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> OverlayServer:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def serve_forever(
    state: OverlayState, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> None:
    """Serve one fixed snapshot until interrupted."""
    server = OverlayServer(lambda: state, host=host, port=port).start()
    print(f"Overlay on {server.url}  (ctrl-c to stop)")
    print("Read-only: GET / and GET /api/state, nothing else.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.stop()


def main() -> None:
    from agents.brain import demo as brain_demo
    from console.briefing import build_overlay_state
    from core.config import Settings
    from core.console import configure_stdout

    configure_stdout()
    report = brain_demo.run(Settings.from_env())
    serve_forever(build_overlay_state(report))


if __name__ == "__main__":
    main()
