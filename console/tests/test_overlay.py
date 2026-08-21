"""Tests for the rendered heads-up display."""

from __future__ import annotations

import json
import re

from agents.brain.models import Verdict
from console.models import Channel, OverlayCard, OverlayState, Utterance
from console.overlay import render_overlay


def state(**overrides) -> OverlayState:
    base = {
        "heading": "Morning brief — Friday 06 March 2026",
        "subheading": "covering Thursday 05 March",
        "approved": 7,
        "held": 8,
        "blocked": 2,
        "autonomy_rate": 0.41,
        "cost_usd": 0.0254,
        "cards": [
            OverlayCard(
                decision_id="dec-1",
                agent="lead-research",
                subject="Outreach: Kestrel Systems",
                verdict=Verdict.BLOCKED,
                reasons=["A2 Honesty: repeats an unverified claim"],
                recipient="d.reyes@kestrel-systems.example",
            )
        ],
        "tasks": ["[urgent] Ring Alpina back"],
        "utterances": [
            Utterance(id="u1", display_text="shown", spoken_text="spoken aloud"),
            Utterance(id="u2", display_text="screen only", channel=Channel.DISPLAY),
        ],
    }
    return OverlayState(**{**base, **overrides})


def embedded_state(html: str) -> dict:
    match = re.search(r'<script id="state" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert match, "no embedded state found"
    return json.loads(match.group(1).replace("<\\/", "</"))


# --- Self-containment ---------------------------------------------------


def test_the_page_is_one_self_contained_document():
    html = render_overlay(state())

    assert html.startswith("<!doctype html>")
    assert "</html>" in html.strip()[-10:]


def test_nothing_is_loaded_from_the_network():
    # No CDN, no external stylesheet, no font host: the overlay has to work
    # with the network unplugged.
    html = render_overlay(state())

    assert "http://" not in html.replace("http://127.0.0.1", "")
    assert "https://" not in html
    assert "<link" not in html


def test_the_heading_and_counts_are_rendered():
    html = render_overlay(state())

    assert "Morning brief" in html
    payload = embedded_state(html)
    assert (payload["approved"], payload["held"], payload["blocked"]) == (7, 8, 2)


def test_each_card_carries_its_verdict_tone():
    payload = embedded_state(render_overlay(state()))
    assert payload["cards"][0]["tone"] == "block"


# --- Safety -------------------------------------------------------------


def test_the_overlay_offers_no_way_to_act():
    # The claim the package README makes. A display with controls would be a
    # second path around the codex.
    html = render_overlay(state()).lower()

    for control in ("<form", "<button", "<input", 'method="post"', "xhr"):
        assert control not in html


def test_a_subject_containing_markup_cannot_break_out():
    html = render_overlay(
        state(
            cards=[
                OverlayCard(
                    decision_id="d",
                    agent="a",
                    subject="</script><img src=x onerror=alert(1)>",
                    verdict=Verdict.APPROVED,
                )
            ]
        )
    )

    # The closing tag is escaped inside the JSON island, so the script block
    # cannot be terminated early by decision text.
    assert "</script><img" not in html
    assert embedded_state(html)["cards"][0]["subject"] == "</script><img src=x onerror=alert(1)>"


def test_a_heading_containing_markup_is_escaped():
    html = render_overlay(state(heading="<b>bold</b>"))
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html


# --- Static versus live -------------------------------------------------


def test_a_static_render_does_not_poll():
    html = render_overlay(state())
    assert 'const endpoint = "";' in html


def test_a_live_render_polls_the_read_only_endpoint():
    html = render_overlay(state(), endpoint="/api/state")
    assert 'const endpoint = "/api/state";' in html
    assert "setInterval" in html


def test_display_only_lines_are_excluded_from_the_spoken_summary():
    html = render_overlay(state())
    # The filter lives in the page script; the data it filters on must survive.
    payload = embedded_state(html)
    channels = [u["channel"] for u in payload["utterances"]]
    assert channels == ["both", "display"]


def test_an_empty_state_still_renders():
    html = render_overlay(OverlayState())
    assert "<!doctype html>" in html
