"""Live Google providers: Calendar, Gmail and Drive.

Nothing here imports at module load. The Google client libraries are an
optional extra (`uv sync --extra google`), and a fresh clone with no accounts
must still run every demo — so the imports are inside the classes that need
them and the agents keep their mocks until somebody connects an account.

    python -m integrations.google.connect    # once, interactively
    python -m integrations.google.check      # prove it works

See `docs/INTEGRATIONS.md` for exactly what to supply.
"""

from __future__ import annotations

from integrations.google.auth import (
    CALENDAR_SCOPES,
    DRIVE_SCOPES,
    GMAIL_SCOPES,
    SCOPES,
    SEND_SCOPE,
    GoogleNotConfigured,
    is_connected,
)

__all__ = [
    "CALENDAR_SCOPES",
    "DRIVE_SCOPES",
    "GMAIL_SCOPES",
    "SCOPES",
    "SEND_SCOPE",
    "GoogleNotConfigured",
    "is_connected",
]
