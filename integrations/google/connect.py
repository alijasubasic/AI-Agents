"""Connect a Google account, once, interactively.

    python -m integrations.google.connect

Opens a browser, asks you to approve the scopes, and writes a token to
`GOOGLE_TOKEN_PATH`. Nothing else in this repository ever starts a consent
flow: a library call that silently opens a browser is one that hangs a
background job forever, so connecting is a thing a person does on purpose.

**What this asks for, and what it deliberately does not.**

    calendar.readonly   free/busy — when someone is unavailable, not what for
    calendar.events     create and update events
    gmail.modify        read messages and change their labels
    drive.file          only files this application itself created

Not `drive` (everything in your Drive), not `gmail.full` (settings and
filters), and not `gmail.send`. Sending mail is a separate flag:

    python -m integrations.google.connect --allow-send

Run it without that first. The agents are useful reading and labelling; the
send path is the only one that reaches another person, and it should be turned
on by somebody who meant to.
"""

from __future__ import annotations

import argparse
import sys

from core.console import configure_stdout
from integrations.google.auth import (
    CLIENT_SECRETS_ENV,
    SCOPES,
    SEND_SCOPE,
    TOKEN_ENV,
    GoogleNotConfigured,
    client_secrets_path,
    save_credentials,
    token_path,
)


def run(*, allow_send: bool = False, port: int = 0) -> str:
    """Do the consent flow and store the token. Returns where it landed."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise GoogleNotConfigured(
            "The Google client libraries are not installed. Run: uv sync --extra google"
        ) from exc

    scopes = list(SCOPES) + ([SEND_SCOPE] if allow_send else [])
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path()), scopes)

    print("\nA browser window will open. Approve the scopes listed above.")
    print("If it does not open, copy the URL it prints.\n")
    # `port=0` lets the OS pick a free loopback port. A fixed port collides
    # with whatever else is listening and fails with a message about sockets
    # rather than about Google.
    credentials = flow.run_local_server(port=port, prompt="consent")

    written = save_credentials(credentials)
    return str(written)


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m integrations.google.connect",
        description="Authorise this machine to use your Google account.",
    )
    parser.add_argument(
        "--allow-send",
        action="store_true",
        help="also request permission to SEND mail (off by default)",
    )
    parser.add_argument("--port", type=int, default=0, help="loopback port (default: any free one)")
    args = parser.parse_args()

    print("=" * 72)
    print("Connecting a Google account")
    print("=" * 72)
    print(f"  client secrets: ${CLIENT_SECRETS_ENV}")
    print(f"  token goes to:  ${TOKEN_ENV}")
    print("\n  Scopes requested:")
    for scope in SCOPES:
        print(f"    - {scope.rsplit('/', 1)[-1]}")
    if args.allow_send:
        print(f"    - {SEND_SCOPE.rsplit('/', 1)[-1]}   <-- can send mail as you")

    try:
        written = run(allow_send=args.allow_send, port=args.port)
    except GoogleNotConfigured as problem:
        # These messages are written to be acted on. Printing the exception
        # class as well would bury the instruction in a traceback.
        print(f"\n  Not connected: {problem}\n")
        return 1

    print(f"\n  Connected. Token written to {written}")
    print("  That file is a credential. It is outside the repository and")
    print("  git-ignored; do not move it into one, and do not commit it.\n")
    print("  Check it worked:  python -m integrations.google.check")
    return 0


def check() -> int:
    """`python -m integrations.google.check` — prove the token actually works.

    Makes one real, read-only call against each API. A token file that exists
    proves somebody ran the flow; only a call proves the scopes are right and
    the refresh token still works.
    """
    configure_stdout()
    print("Checking the Google connection — three read-only calls.\n")

    try:
        path = token_path()
    except GoogleNotConfigured as problem:
        print(f"  {problem}")
        return 1
    print(f"  token: {path}")

    failures = 0
    for label, probe in (
        ("calendar", _probe_calendar),
        ("gmail", _probe_gmail),
        ("drive", _probe_drive),
    ):
        try:
            detail = probe()
            print(f"  [ ok ] {label:<9} {detail}")
        except Exception as problem:  # noqa: BLE001 - reported, not swallowed
            failures += 1
            print(f"  [FAIL] {label:<9} {type(problem).__name__}: {str(problem)[:90]}")

    print()
    if failures:
        print(f"  {failures} of 3 failed. Re-run `python -m integrations.google.connect`.")
        return 1
    print("  All three answered. The agents can use this account.")
    return 0


def _probe_calendar() -> str:
    from integrations.google.auth import CALENDAR_SCOPES, service

    result = (
        service("calendar", "v3", scopes=CALENDAR_SCOPES)
        .calendarList()
        .list(maxResults=1)
        .execute()
    )
    return f"{len(result.get('items', []))} calendar(s) visible"


def _probe_gmail() -> str:
    from integrations.google.auth import GMAIL_SCOPES, service

    profile = service("gmail", "v1", scopes=GMAIL_SCOPES).users().getProfile(userId="me").execute()
    return f"{profile.get('messagesTotal', 0)} messages in the mailbox"


def _probe_drive() -> str:
    from integrations.google.auth import DRIVE_SCOPES, service

    result = (
        service("drive", "v3", scopes=DRIVE_SCOPES)
        .files()
        .list(pageSize=1, fields="files(id)")
        .execute()
    )
    return f"{len(result.get('files', []))} app-owned file(s)"


if __name__ == "__main__":
    sys.exit(main())
