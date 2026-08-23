"""The palette, in one place.

Taken from the source dashboard, which is worth saying plainly: the cyan-on-
near-black arc-reactor look is that project's design and this reproduces it.
What is not taken is the mechanism — there it is a JS object merged with user
config at render time, here it is CSS custom properties, because the page has
no framework to merge anything with and a stylesheet variable is the browser's
own version of the same idea.

The four state colours are shared with the rest of the console on purpose.
`ok` / `hold` / `block` mean the same thing on a codex verdict, a task status
and a diagnostics check, so an operator learns one mapping rather than three.
"""

from __future__ import annotations

#: name -> CSS value. Emitted as `--name` on `:root`.
PALETTE: dict[str, str] = {
    "bg": "#0a0a14",
    "panel": "#0d1117",
    "panel-2": "#12182a",
    "line": "rgba(0, 212, 255, 0.14)",
    "line-soft": "rgba(0, 212, 255, 0.07)",
    "accent": "#00d4ff",
    "accent-dim": "rgba(0, 212, 255, 0.30)",
    "accent-faint": "rgba(0, 212, 255, 0.08)",
    "purple": "#7c6bff",
    "ok": "#44c98f",
    "hold": "#f6d365",
    "block": "#e05561",
    "warn": "#ff6b35",
    "text": "#e0e6ed",
    "muted": "#6b7b8d",
    "dim": "#3a4553",
}


def css_variables() -> str:
    """The palette as a `:root` block."""
    body = "\n".join(f"  --{name}: {value};" for name, value in PALETTE.items())
    return ":root {\n" + body + "\n}"
