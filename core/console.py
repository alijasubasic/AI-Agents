"""Console output helpers for the demo scripts.

Python picks stdout's encoding from the environment. Attached to a terminal on
Windows it writes through the console API and handles anything; redirected into
a pipe it falls back to the locale encoding, which on a German Windows install
is cp1252 — and a single emoji in a fixture then kills the process with a
UnicodeEncodeError.

That is a poor way for a repository promising "clone it and run it" to fail, so
the demos widen stdout before printing anything.
"""

from __future__ import annotations

import contextlib
import sys


def configure_stdout() -> None:
    """Make stdout accept non-ASCII regardless of how the process was launched.

    Best effort by design: if the stream cannot be reconfigured there is nothing
    useful to do about it, and a demo must not fail while setting up to print.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # Platform dependent: some streams refuse reconfiguration outright.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")
