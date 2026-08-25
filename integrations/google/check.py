"""`python -m integrations.google.check` — prove the connection works.

Split from `connect` so the two verbs are two commands. A token file that
exists proves somebody ran the consent flow; only a real call proves the
scopes are right and the refresh token still works.
"""

from __future__ import annotations

import sys

from integrations.google.connect import check

if __name__ == "__main__":
    sys.exit(check())
