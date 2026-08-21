"""Tests for the overlay server.

Most of this file exists to check one thing: **the server cannot act.** That is
the claim the package README makes, and it is only true while every mutating
method is refused.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from agents.brain.models import Verdict
from console.models import OverlayCard, OverlayState
from console.server import OverlayServer


def state() -> OverlayState:
    return OverlayState(
        heading="Morning brief",
        subheading="covering Thursday",
        approved=7,
        held=8,
        blocked=2,
        autonomy_rate=0.41,
        cost_usd=0.0254,
        cards=[
            OverlayCard(
                decision_id="dec-1",
                agent="lead-research",
                subject="Outreach: Kestrel Systems",
                verdict=Verdict.BLOCKED,
                reasons=["A2 Honesty: repeats an unverified claim"],
            )
        ],
        tasks=["[urgent] Review: Call call-002"],
    )


@pytest.fixture
def server():
    with OverlayServer(state, port=0) as running:
        yield running


def fetch(url: str, *, method: str = "GET") -> tuple[int, bytes]:
    request = urllib.request.Request(url, method=method)  # noqa: S310 - localhost
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# --- The two routes it has ----------------------------------------------


def test_the_root_serves_the_overlay(server):
    status, body = fetch(server.url)

    assert status == 200
    assert b"<!doctype html>" in body
    assert b"Morning brief" in body


def test_the_state_endpoint_serves_json(server):
    status, body = fetch(server.url + "api/state")
    payload = json.loads(body)

    assert status == 200
    assert payload["approved"] == 7
    assert payload["cards"][0]["subject"] == "Outreach: Kestrel Systems"


def test_a_trailing_slash_does_not_matter(server):
    assert fetch(server.url + "api/state/")[0] == 200


def test_a_query_string_does_not_matter(server):
    assert fetch(server.url + "api/state?t=1")[0] == 200


def test_an_unknown_path_is_a_clean_404(server):
    status, _ = fetch(server.url + "admin")
    assert status == 404


# --- The routes it deliberately does not have ---------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_mutating_method_is_refused(server, method):
    # A display that can also act is a second way to approve something, and one
    # that never passes through the codex or lands in the audit trail.
    status, _ = fetch(server.url, method=method)
    assert status == 405


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_mutating_methods_are_refused_on_the_api_too(server, method):
    status, _ = fetch(server.url + "api/state", method=method)
    assert status == 405


def test_a_refusal_advertises_what_is_allowed(server):
    request = urllib.request.Request(server.url, method="POST")  # noqa: S310
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=5)  # noqa: S310

    assert caught.value.headers["Allow"] == "GET, HEAD"


# --- Serving -------------------------------------------------------------


def test_the_snapshot_is_refetched_rather_than_frozen():
    # The server holds no state of its own; it asks the provider every time.
    calls = {"n": 0}

    def counting_provider() -> OverlayState:
        calls["n"] += 1
        return state()

    with OverlayServer(counting_provider, port=0) as running:
        fetch(running.url + "api/state")
        fetch(running.url + "api/state")

    assert calls["n"] == 2


def test_responses_are_not_cached(server):
    request = urllib.request.Request(server.url + "api/state")  # noqa: S310
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        assert response.headers["Cache-Control"] == "no-store"


def test_the_server_binds_to_localhost_only():
    # Binding to 0.0.0.0 would put an unauthenticated view of the company's
    # decisions on the local network.
    with OverlayServer(state, port=0) as running:
        assert running.url.startswith("http://127.0.0.1:")
