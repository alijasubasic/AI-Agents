"""One place that knows about Google credentials.

Every Google client in this repository gets its session from here, and nothing
else touches a token. That is worth the indirection for one reason: credential
handling is the part of an integration that goes wrong quietly, and code that
is written twice is written differently twice.

**Scopes are minimal, and they are listed rather than assembled.** Google will
happily grant `https://www.googleapis.com/auth/drive`, which is read-write
access to everything in the account. This asks for `drive.file` instead — only
files this application itself created. If the token leaks, the blast radius is
the notes this repository wrote, not the user's documents. The same reasoning
picks `calendar.events` over `calendar` and `gmail.modify` over `gmail.full`.

**Sending is off by default.** `SCOPES` does not include `gmail.send`. An agent
that can read mail and label it is useful; an agent that can email a customer
because a config file was wrong is an incident. Turning it on is a deliberate
act — see `SEND_SCOPE` and `docs/INTEGRATIONS.md`.

The optional dependency is real: without `uv sync --extra google` nothing here
imports, and every agent keeps running against its mock. That is the point of
the extra — a fresh clone must work with no accounts at all.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

#: Read-only calendar access, plus the ability to create events.
#:
#: `calendar.readonly` is what free/busy needs. `calendar.events` allows
#: creating and updating events but *not* reading anyone's calendar settings,
#: deleting calendars, or changing sharing.
CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)

#: Read messages and change their labels. Not `gmail.full`, which also grants
#: settings and filter management.
GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.modify",)

#: Files this application created, and nothing else in the user's Drive.
DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)

#: Deliberately not in `SCOPES`. Adding it is what lets an agent send mail.
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

#: What `python -m integrations.google.connect` asks for by default.
SCOPES: tuple[str, ...] = CALENDAR_SCOPES + GMAIL_SCOPES + DRIVE_SCOPES

#: Where the OAuth client file downloaded from Google Cloud lives.
CLIENT_SECRETS_ENV = "GOOGLE_CLIENT_SECRETS"

#: Where the token produced by the consent flow is stored. Git-ignored.
TOKEN_ENV = "GOOGLE_TOKEN_PATH"


class GoogleNotConfigured(RuntimeError):
    """Raised with an instruction, not a stack trace.

    Every message from this module tells the reader the next thing to do. A
    missing-credentials error that says `FileNotFoundError` sends somebody to
    a search engine; one that names the environment variable and the command
    sends them to the fix.
    """


def client_secrets_path() -> Path:
    configured = os.environ.get(CLIENT_SECRETS_ENV, "").strip()
    if not configured:
        raise GoogleNotConfigured(
            f"{CLIENT_SECRETS_ENV} is not set. Download the OAuth client JSON from "
            "Google Cloud Console -> APIs & Services -> Credentials, save it "
            "outside this repository, and point the variable at it. "
            "See docs/INTEGRATIONS.md."
        )
    path = Path(configured)
    if not path.is_file():
        raise GoogleNotConfigured(f"{CLIENT_SECRETS_ENV} points at {path}, which does not exist.")
    return path


def token_path() -> Path:
    configured = os.environ.get(TOKEN_ENV, "").strip()
    if not configured:
        raise GoogleNotConfigured(
            f"{TOKEN_ENV} is not set. Choose a path outside this repository — "
            "it holds a refresh token — and run "
            "`python -m integrations.google.connect`."
        )
    return Path(configured)


def _require_libraries():
    """Import the Google client libraries, or explain how to get them."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise GoogleNotConfigured(
            "The Google client libraries are not installed. Run: uv sync --extra google"
        ) from exc
    return Credentials, Request, InstalledAppFlow, build


def load_credentials(scopes: tuple[str, ...] | None = None):
    """The stored credentials, refreshed if they have expired.

    Never starts a consent flow. A library call that silently opens a browser
    is a library call that hangs a background job forever — connecting is an
    explicit, interactive act, and it lives in `connect.py`.
    """
    Credentials, Request, _flow, _build = _require_libraries()
    path = token_path()
    if not path.is_file():
        raise GoogleNotConfigured(
            f"No token at {path}. Run `python -m integrations.google.connect` once; "
            "it opens a browser, you approve, and it writes the token."
        )

    credentials = Credentials.from_authorized_user_file(str(path), list(scopes or SCOPES))
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        save_credentials(credentials)
    if not credentials.valid:
        raise GoogleNotConfigured(
            f"The token at {path} is not usable. Delete it and run "
            "`python -m integrations.google.connect` again."
        )
    return credentials


def save_credentials(credentials) -> Path:
    """Write the token, with permissions that assume other people exist.

    `0o600` on anything POSIX. Windows ignores the mode, which is worth knowing
    rather than pretending otherwise — on Windows the protection is that the
    path is outside the repository and therefore outside anything git can
    commit or a build can archive.
    """
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")
    with contextlib.suppress(OSError, NotImplementedError):  # Windows ignores it
        path.chmod(0o600)
    return path


def service(api: str, version: str, *, scopes: tuple[str, ...] | None = None):
    """A built Google API client.

    `cache_discovery=False` because the default on-disk discovery cache writes
    into the working directory and warns on every start under Python 3.
    """
    _credentials, _request, _flow, build = _require_libraries()
    return build(
        api,
        version,
        credentials=load_credentials(scopes),
        cache_discovery=False,
    )


def is_connected() -> bool:
    """Whether a token file exists. Deliberately no more than that.

    Opening the token to check its scopes would mean reading a credential to
    answer a cosmetic question, and an expired refresh token looks identical
    to a working one until a call is made. The dashboard shows "connected";
    the first real call is what proves it.
    """
    configured = os.environ.get(TOKEN_ENV, "").strip()
    return bool(configured) and Path(configured).is_file()
