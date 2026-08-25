"""How the dashboard looks.

The split this package exists for: `jarvis/*.py` is what the dashboard *knows*
— the fleet, the graph, the telemetry, the guardrails — and `jarvis/ui/` is how
it is drawn. Nothing here reaches for data, and nothing there knows a colour.

    theme.py     design tokens, the only place a hex value is written
    styles.py    the stylesheet
    sphere.py    the force-directed graph
    scripts.py   the client
    layout.py    the page skeleton

One self-contained page comes out of `render_dashboard`. No framework, no build
step, no CDN — the server's Content-Security-Policy forbids external origins,
and a test asserts the page contains no `https://` at all.
"""

from __future__ import annotations

import json

from jarvis.panels import Dashboard
from jarvis.ui.layout import TEMPLATE
from jarvis.ui.scripts import APP_JS
from jarvis.ui.sphere import SPHERE_JS
from jarvis.ui.styles import stylesheet
from jarvis.ui.theme import TOKENS

__all__ = ["TOKENS", "embed_json", "render_dashboard", "stylesheet"]


def embed_json(payload: dict) -> str:
    """Serialise a payload for embedding inside a `<script>` block.

    `json.dumps` alone is not safe here, and the difference is a real hole
    rather than a theoretical one: it escapes quotes but leaves `<` and `>`
    alone, so a task containing the literal `</script>` ends the block early
    and everything after it is parsed as markup — on a page the operator
    trusts, from a string an agent or a caller supplied.

    Escaping the three characters as `\\uXXXX` is still valid JSON, parses to
    the same value, and cannot close a tag.
    """
    return (
        json.dumps(payload).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


def render_dashboard(dashboard: Dashboard) -> str:
    """The whole dashboard as one self-contained HTML page.

    The template carries no data. Every value — including the capture path,
    which the previous version HTML-escaped on its way into the markup —
    reaches the page inside the bootstrap payload and is written with
    `textContent`. That escaping was not only unnecessary once the value
    stopped touching markup, it was *wrong*: a path containing `&` would have
    displayed as `&amp;`. Escaping something that is never parsed as HTML
    corrupts it.
    """
    return TEMPLATE.format(
        css=stylesheet(),
        sphere_js=SPHERE_JS,
        app_js=APP_JS,
        bootstrap=embed_json(dashboard.model_dump(mode="json")),
    )
