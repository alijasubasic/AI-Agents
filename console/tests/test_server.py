"""Tests for the console's HTTP surface.

The route table is the security boundary here, so it is asserted directly:
adding an endpoint that approves, sends or overrides something has to fail a
test rather than pass unnoticed in review.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from agents.brain import demo as brain_demo
from console.briefing import build_overlay_state
from console.chat_demo import build_session
from console.server import MAX_BODY_BYTES, ROUTES, build_handler
from console.tasks import TaskStatus
from core.config import Settings


def settings() -> Settings:
    return Settings(trace_enabled=False)


@pytest.fixture
def console():
    """A running console on a throwaway port."""
    session = build_session(settings())
    state = build_overlay_state(brain_demo.run(settings()))

    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(session, lambda: state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, session
    finally:
        server.shutdown()
        server.server_close()


def get(base: str, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=10) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def post(base: str, path: str, payload: dict | bytes) -> tuple[int, str]:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310
        f"{base}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


# --- The route table ----------------------------------------------------


def test_the_route_table_is_exactly_four_routes():
    assert set(ROUTES) == {
        ("GET", "/"),
        ("GET", "/api/state"),
        ("POST", "/api/task"),
        ("POST", "/api/answer"),
    }


def test_no_route_approves_sends_books_or_overrides():
    # The invariant this whole design rests on. A new endpoint named any of
    # these fails here before anyone has to notice it in review.
    forbidden = ("approve", "send", "book", "override", "verdict", "merge", "confirm")
    for _method, path in ROUTES:
        assert not any(word in path.lower() for word in forbidden), path


def test_an_unknown_route_is_refused(console):
    base, _ = console
    status, body = get(base, "/api/approve")

    assert status == 404
    assert "no such route" in body


def test_an_unknown_post_route_is_refused(console):
    base, _ = console
    status, _body = post(base, "/api/approve", {"task_id": "x"})
    assert status == 404


# --- Serving ------------------------------------------------------------


def test_the_console_page_is_self_contained(console):
    base, _ = console
    status, body = get(base, "/")

    assert status == 200
    assert "<!doctype html>" in body.lower()
    # A strict CSP is pointless if the page needs a CDN anyway.
    assert "https://" not in body
    assert "cdn." not in body


def test_the_state_endpoint_returns_the_render_payload(console):
    base, _ = console
    status, body = get(base, "/api/state")
    payload = json.loads(body)

    assert status == 200
    assert set(payload) >= {"turns", "questions", "cards", "agents", "open_tasks"}


# --- Creating work ------------------------------------------------------


def test_a_task_can_be_created(console):
    base, session = console
    status, body = post(base, "/api/task", {"request": "Research Kestrel Systems"})

    assert status == 200
    assert session.conversation.tasks
    assert json.loads(body)["turns"]


def test_an_empty_request_is_rejected(console):
    base, session = console
    status, body = post(base, "/api/task", {"request": "   "})

    assert status == 400
    assert "empty" in body
    assert session.conversation.tasks == []


def test_a_question_can_be_answered_over_http(console):
    base, session = console
    post(base, "/api/task", {"request": "profile that company we spoke to"})

    task = session.conversation.tasks[-1]
    assert task.status.waits_on_operator

    status, _body = post(
        base,
        "/api/answer",
        {
            "task_id": task.id,
            "question_id": task.open_questions[0].id,
            "text": "Kestrel Systems",
        },
    )

    assert status == 200
    assert task.status is not TaskStatus.NEEDS_CLARIFICATION


def test_answering_an_unknown_task_is_refused(console):
    base, _ = console
    status, body = post(base, "/api/answer", {"task_id": "nope", "question_id": "q", "text": "x"})

    assert status == 404
    assert "no such task" in body


def test_an_incomplete_answer_is_refused(console):
    base, _ = console
    status, _body = post(base, "/api/answer", {"task_id": "t", "question_id": "q"})
    assert status == 400


# --- Input handling -----------------------------------------------------


def test_a_body_that_is_not_json_is_refused(console):
    base, _ = console
    status, _body = post(base, "/api/task", b"not json at all")
    assert status == 400


def test_a_json_array_is_refused(console):
    # Valid JSON, wrong shape. `payload.get` on a list would raise.
    base, _ = console
    status, _body = post(base, "/api/task", b'["not", "an", "object"]')
    assert status == 400


def test_an_oversized_body_is_refused_unread(console):
    base, session = console
    status, _body = post(base, "/api/task", json.dumps({"request": "x" * MAX_BODY_BYTES}).encode())

    assert status == 400
    assert session.conversation.tasks == []


def test_html_in_a_request_is_not_reflected_as_markup(console):
    # Everything the page renders goes through textContent, but the payload is
    # worth checking too: a task subject reaches the sidebar of a page the
    # operator trusts.
    base, _ = console
    post(base, "/api/task", {"request": "<script>alert(1)</script> research something"})

    _status, body = get(base, "/api/state")
    payload = json.loads(body)
    turns = " ".join(turn["text"] for turn in payload["turns"])

    # Stored verbatim as data — the escaping happens at render time, not by
    # mangling what the operator typed.
    assert "<script>" in turns
    _status, page = get(base, "/")
    assert "<script>alert(1)</script>" not in page


def test_a_script_tag_in_a_task_cannot_close_the_bootstrap_block(console):
    """The hole this escaping exists for.

    json.dumps escapes quotes but not angle brackets, so a task containing the
    literal `</script>` ended the bootstrap block early and everything after it
    was parsed as markup — on a page the operator trusts.
    """
    base, _ = console
    post(base, "/api/task", {"request": "</script><img src=x onerror=alert(1)> research"})

    _status, page = get(base, "/")

    # The payload still carries the text; it just cannot close the tag.
    assert "\u003c/script\u003e" in page
    assert "</script><img" not in page
    # Exactly the two script blocks the template defines.
    assert page.count("</script>") == 2
