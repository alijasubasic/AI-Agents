"""Design tokens.

Every colour, radius and space in the interface is named here and used through
a CSS custom property. Nothing downstream writes a hex value, which is what
makes a restyle a change to one file rather than a search across four.

The palette is deliberately short. An earlier version had fourteen colours and
used all of them, so nothing on screen meant anything — a border was cyan
because borders were cyan. Here **colour carries state and nothing else**:

    accent   the one thing you are meant to look at
    ok       approved, connected, passing
    hold     waiting on a person
    block    refused, and it will not proceed

Everything else is one of four greys. If a new element needs a fifth grey, the
layout is wrong rather than the palette being short.
"""

from __future__ import annotations

#: name -> CSS value, emitted as `--name` on `:root`.
TOKENS: dict[str, str] = {
    # --- ground ---------------------------------------------------------
    "bg": "#090b0f",
    "surface": "#0f1319",
    "raised": "#151a22",
    "line": "#1b2029",
    "line-strong": "#28303c",
    # --- ink ------------------------------------------------------------
    "text": "#e7eaf0",
    "muted": "#8a95a6",
    "dim": "#4e5867",
    "faint": "#2e3644",
    # --- meaning --------------------------------------------------------
    "accent": "#4dd4ff",
    "accent-soft": "rgba(77, 212, 255, 0.10)",
    "accent-line": "rgba(77, 212, 255, 0.28)",
    #: Ink on an accent-filled control, and the lift on hover. Dark enough on
    #: the accent to pass contrast; there is nowhere else these belong.
    "accent-ink": "#04222d",
    "accent-lift": "#6cdcff",
    "ok": "#4fc98d",
    "hold": "#e8bd5b",
    "block": "#e2615f",
    # --- metrics --------------------------------------------------------
    "rail": "216px",
    "radius": "10px",
    "radius-sm": "6px",
}


def css_variables() -> str:
    """The tokens as a `:root` block."""
    body = "\n".join(f"  --{name}: {value};" for name, value in TOKENS.items())
    return ":root {\n" + body + "\n}"
