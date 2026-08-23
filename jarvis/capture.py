"""Quick capture: a note from the dashboard into the Obsidian vault.

This is the one route in the whole console that *writes* something, so it is
worth being explicit about why it does not break the rule the rest of the
design rests on.

    The console may create work; it has no route that approves any.

A captured note approves nothing, sends nothing, books nothing and overrides
nothing. It writes Markdown into a folder on this machine. That is the same
category as typing a task — creating a record, not authorising an action.

What it is *not* allowed to do:

* **write outside one folder.** The folder is fixed in code, not taken from the
  request. A `folder` field in the payload would be a directory traversal with
  extra steps.
* **choose its own filename.** The slug is derived from the title, and
  `ObsidianVault` takes `Path(filename).stem` before sanitising it, so any
  directory part is gone before the name is used. `ObsidianVault._target` then
  resolves the whole path and refuses it if it left the vault.
* **grow without limit.** A body over a few kilobytes is refused, matching the
  cap the server already puts on request bodies.
"""

from __future__ import annotations

from datetime import UTC, datetime

from console.models import VaultNote
from console.vault import VaultWriter, safe_slug

#: Every captured note lands here. Not configurable from the request.
FOLDER = "Captures"

#: Titles longer than this are cut. Obsidian copes; Windows explorer does not.
MAX_TITLE = 80

#: A capture is a thought, not a document.
MAX_BODY = 4000


class CaptureRefused(ValueError):
    """The note was not written, and the reason is safe to show the operator."""


def build_note(title: str, body: str, *, now: datetime | None = None) -> VaultNote:
    """Turn a title and a body into a note that is safe to write.

    The timestamp goes in the slug rather than only in the frontmatter. Two
    captures with the same title on the same day are two different thoughts,
    and a stable slug would silently overwrite the first — which is the right
    behaviour for a decision record and the wrong one for a scratch note.
    """
    body = body.strip()
    if not body:
        raise CaptureRefused("a capture needs a body")
    if len(body) > MAX_BODY:
        raise CaptureRefused(f"a capture is capped at {MAX_BODY} characters")

    now = now or datetime.now(UTC)
    stamp = now.astimezone().strftime("%Y-%m-%d %H%M")
    heading = safe_slug(title.strip() or "Capture", max_length=MAX_TITLE)

    return VaultNote(
        slug=f"{stamp} {heading}",
        folder=FOLDER,
        title=heading,
        frontmatter={
            "captured": now.isoformat(),
            "source": "jarvis-dashboard",
            "tags": ["capture"],
        },
        body=body,
        links=["Daily brief"],
    )


def capture(vault: VaultWriter, title: str, body: str, *, now: datetime | None = None) -> str:
    """Write one note and return where it landed."""
    return vault.write(build_note(title, body, now=now))
