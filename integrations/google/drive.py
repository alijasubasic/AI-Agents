"""Google Drive, as a place the morning brief lands.

Drive is the one integration here that is purely outbound: nothing reads from
it, and no agent decision depends on it. It exists so the brief and its
spreadsheet are somewhere a person can open on a phone.

**Scope is `drive.file`, and that choice is the whole security story.** It
grants access only to files this application itself created — not the user's
documents, not their shared drives, not anything they made in a browser. If
the token leaks, what is exposed is the briefs this repository wrote. The
wider `drive` scope would have been one word shorter and is not worth it.

**Uploads are idempotent by name within one folder.** A brief re-run for the
same day updates its file rather than adding `brief (2)`. An audit trail that
duplicates on every run is one nobody trusts.
"""

from __future__ import annotations

from pathlib import Path

from integrations.google.auth import DRIVE_SCOPES, service

#: The folder created in the user's Drive root the first time anything uploads.
DEFAULT_FOLDER = "AI Agent Briefs"

_MIME = {
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".json": "application/json",
    ".txt": "text/plain",
}


class GoogleDrive:
    """Uploads files into one folder this application owns."""

    def __init__(self, *, folder_name: str = DEFAULT_FOLDER) -> None:
        self._folder_name = folder_name
        self._folder_id: str | None = None
        self._service = service("drive", "v3", scopes=DRIVE_SCOPES)

    # -- folders ---------------------------------------------------------

    def folder_id(self) -> str:
        """The destination folder, created once and then remembered.

        Searched by name *among files this app created* — which is all
        `drive.file` can see, and is exactly the right restriction: a folder
        the user made called "AI Agent Briefs" is invisible here and will not
        be written into by accident.
        """
        if self._folder_id:
            return self._folder_id

        query = (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{self._folder_name}' and trashed = false"
        )
        found = self._service.files().list(q=query, fields="files(id)", pageSize=1).execute()
        files = found.get("files", [])

        if files:
            self._folder_id = files[0]["id"]
        else:
            created = (
                self._service.files()
                .create(
                    body={
                        "name": self._folder_name,
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                    fields="id",
                )
                .execute()
            )
            self._folder_id = created["id"]
        return self._folder_id

    # -- files -----------------------------------------------------------

    def upload(self, path: Path | str, *, name: str | None = None) -> str:
        """Upload or replace one file. Returns its Drive id."""
        from googleapiclient.http import MediaFileUpload

        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)

        name = name or path.name
        media = MediaFileUpload(
            str(path),
            mimetype=_MIME.get(path.suffix.lower(), "application/octet-stream"),
            resumable=False,
        )

        existing = self._find(name)
        if existing:
            updated = (
                self._service.files()
                .update(fileId=existing, media_body=media, fields="id")
                .execute()
            )
            return updated["id"]

        created = (
            self._service.files()
            .create(
                body={"name": name, "parents": [self.folder_id()]},
                media_body=media,
                fields="id",
            )
            .execute()
        )
        return created["id"]

    def _find(self, name: str) -> str | None:
        escaped = name.replace("'", "\\'")
        query = f"name = '{escaped}' and '{self.folder_id()}' in parents and trashed = false"
        found = self._service.files().list(q=query, fields="files(id)", pageSize=1).execute()
        files = found.get("files", [])
        return files[0]["id"] if files else None
