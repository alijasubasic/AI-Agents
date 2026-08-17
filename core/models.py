"""Data models for the agent runtime.

Everything that crosses a boundary — provider responses, tool arguments, trace
records — is a pydantic model. Nothing in this codebase parses an LLM response
by slicing strings.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["user", "assistant"]
StopReason = Literal[
    "end_turn",
    "tool_use",
    "max_tokens",
    "stop_sequence",
    "refusal",
    "pause_turn",
]

#: Every stop reason we model explicitly. Anything the API returns outside this
#: set is normalised to "end_turn" rather than blowing up validation — a new
#: stop reason should not take down a running agent.
KNOWN_STOP_REASONS: frozenset[str] = frozenset(
    ["end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "pause_turn"]
)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --- Conversation primitives -------------------------------------------


class ToolCall(BaseModel):
    """A request from the model to run one tool."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The outcome of running one tool, sent back to the model."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    """One turn of the conversation, in provider-neutral form."""

    role: Role
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)

    #: The provider's own content blocks for an assistant turn, kept verbatim.
    #: Some block types (notably thinking blocks) must be echoed back unchanged
    #: and cannot be reconstructed from the normalised fields above, so we
    #: replay this payload when it is present. None for mock runs.
    raw: list[dict[str, Any]] | None = None


# --- Provider responses ------------------------------------------------


class Usage(BaseModel):
    """Token counts for a single model request."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
        )


class LLMResponse(BaseModel):
    """One model response, normalised across providers."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    stop_reason: StopReason = "end_turn"
    model: str = ""

    #: Verbatim provider content blocks; see :attr:`Message.raw`.
    raw: list[dict[str, Any]] | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


# --- Tracing -----------------------------------------------------------


class Step(BaseModel):
    """One iteration of the agent loop, recorded for the trace log."""

    index: int
    started_at: datetime = Field(default_factory=_now)
    duration_ms: float = 0.0
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    stop_reason: StopReason = "end_turn"


class RunResult(BaseModel):
    """Everything a caller needs to know about one agent run."""

    run_id: str = Field(default_factory=lambda: _new_id("run"))
    agent: str
    model: str
    mode: str
    started_at: datetime = Field(default_factory=_now)
    duration_ms: float = 0.0

    output: str = ""
    steps: list[Step] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0

    #: Set when the run stopped for a reason other than the agent finishing:
    #: a step limit, a timeout, a budget cap, or an unexpected failure.
    halted_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.halted_reason is None

    @property
    def step_count(self) -> int:
        return len(self.steps)
