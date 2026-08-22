"""Runtime configuration.

Every setting has a working default, so the repository runs on a fresh machine
with no `.env` file and no API key. That is the core promise of this project:
`make demo` must produce visible output for anyone who clones it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.dotenv import load as load_dotenv

Mode = Literal["mock", "live"]

#: Default model for every agent. See docs/adr/0003-model-selection.md.
DEFAULT_MODEL = "claude-opus-5"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class Settings(BaseModel):
    """Resolved configuration for a single process."""

    mode: Mode = "mock"
    model: str = DEFAULT_MODEL
    api_key: str | None = None

    # Safety rails. These apply in mock mode too, so the limits themselves are
    # exercised by the test suite rather than only in production.
    max_steps: int = Field(default=8, ge=1, le=100)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_cost_usd: float = Field(default=1.0, gt=0)

    trace_enabled: bool = True
    trace_dir: Path = Path("traces")

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables, falling back to defaults.

        Reads `.env` first, if there is one. The real environment wins over it,
        so CI and an explicit `AGENT_MODE=live make demo` are never overridden
        by a stale file on somebody's machine.
        """
        load_dotenv()

        mode_raw = os.environ.get("AGENT_MODE", "mock").strip().lower()
        mode: Mode = "live" if mode_raw == "live" else "mock"

        return cls(
            mode=mode,
            model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            max_steps=_env_int("AGENT_MAX_STEPS", 8),
            timeout_seconds=_env_float("AGENT_TIMEOUT_SECONDS", 60.0),
            max_cost_usd=_env_float("AGENT_MAX_COST_USD", 1.0),
            trace_enabled=_env_bool("TRACE_ENABLED", True),
            trace_dir=Path(os.environ.get("TRACE_DIR", "traces")),
        )

    @property
    def is_live(self) -> bool:
        return self.mode == "live"
