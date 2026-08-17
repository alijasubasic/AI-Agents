"""LLM providers.

The agent loop talks to a narrow `LLMProvider` interface, never to a vendor SDK
directly. Two implementations exist:

* :class:`MockProvider` — deterministic scripted responses, no network. This is
  the default everywhere, which is why the test suite and `make demo` run on a
  machine with no API key.
* :class:`AnthropicProvider` — the real Claude API.

Swapping between them changes one line of configuration, not any agent code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from core.config import Settings
from core.errors import (
    PermanentProviderError,
    TransientProviderError,
)
from core.models import KNOWN_STOP_REASONS, LLMResponse, Message, ToolCall, Usage


class LLMProvider(Protocol):
    """The only thing the agent loop needs from a model provider."""

    model: str

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse: ...


# --- Mock ---------------------------------------------------------------


class MockProvider:
    """Replays a scripted list of responses.

    Scripted rather than generated on purpose: a fixture that returns the same
    thing every run is what makes the eval scores in `evals/` meaningful. If a
    score moves, the agent changed — not the weather.
    """

    def __init__(
        self,
        responses: Sequence[LLMResponse],
        *,
        model: str = "mock-model",
    ) -> None:
        if not responses:
            raise ValueError("MockProvider needs at least one scripted response")
        self.model = model
        self._responses = list(responses)
        self._index = 0
        #: Every request the agent made, so tests can assert on what was sent.
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        self.calls.append(
            {
                "system": system,
                "messages": [m.model_dump() for m in messages],
                "tools": [t["name"] for t in tools],
                "max_tokens": max_tokens,
            }
        )

        if self._index >= len(self._responses):
            raise PermanentProviderError(
                f"MockProvider ran out of scripted responses after {self._index} "
                f"call(s). Add another response to the fixture."
            )

        response = self._responses[self._index]
        self._index += 1
        return response.model_copy(update={"model": self.model})

    @property
    def remaining(self) -> int:
        return len(self._responses) - self._index


def text_response(text: str, *, output_tokens: int = 24) -> LLMResponse:
    """Shorthand for a scripted final answer."""
    return LLMResponse(
        text=text,
        stop_reason="end_turn",
        usage=Usage(input_tokens=120, output_tokens=output_tokens),
    )


def tool_response(name: str, arguments: dict[str, Any], *, call_id: str = "call_1") -> LLMResponse:
    """Shorthand for a scripted tool call."""
    return LLMResponse(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        stop_reason="tool_use",
        usage=Usage(input_tokens=120, output_tokens=32),
    )


# --- Anthropic ----------------------------------------------------------


class AnthropicProvider:
    """The real Claude API.

    Only constructed when ``AGENT_MODE=live``. The import is deferred so the
    package works without the SDK installed.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise PermanentProviderError(
                "AGENT_MODE=live requires ANTHROPIC_API_KEY. "
                "Unset AGENT_MODE to run against the mock provider instead."
            )

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise PermanentProviderError(
                "The `anthropic` package is required for live mode: uv sync"
            ) from exc

        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=settings.api_key)
        self.model = settings.model

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        try:
            raw = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[_to_api_message(m) for m in messages],
                tools=tools or self._sdk.NOT_GIVEN,
                # Adaptive thinking lets the model decide how much to reason per
                # step; `effort` is the cost/quality dial. Neither is a fixed
                # token budget — see docs/adr/0003-model-selection.md.
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
            )
        except self._sdk.RateLimitError as exc:
            raise TransientProviderError(f"Rate limited: {exc}") from exc
        except self._sdk.APIConnectionError as exc:
            raise TransientProviderError(f"Connection error: {exc}") from exc
        except self._sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientProviderError(f"Server error {exc.status_code}: {exc}") from exc
            raise PermanentProviderError(f"API error {exc.status_code}: {exc}") from exc

        return _from_api_response(raw)


def _to_api_message(message: Message) -> dict[str, Any]:
    """Convert one internal message into the API's content-block format."""
    if message.role == "assistant":
        # Replay the provider's own blocks when we have them. Thinking blocks
        # must be echoed back byte-for-byte, and they cannot be rebuilt from the
        # normalised fields — so the raw payload is the authoritative version.
        if message.raw is not None:
            return {"role": "assistant", "content": message.raw}

        content: list[dict[str, Any]] = []
        if message.text:
            content.append({"type": "text", "text": message.text})
        content.extend(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": call.arguments,
            }
            for call in message.tool_calls
        )
        return {"role": "assistant", "content": content}

    # User turns carry either plain text or the results of the previous step's
    # tool calls. All results for one step go in a single message — splitting
    # them teaches the model to stop making parallel calls.
    if message.tool_results:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_call_id,
                    "content": result.content,
                    "is_error": result.is_error,
                }
                for result in message.tool_results
            ],
        }
    return {"role": "user", "content": message.text}


def _from_api_response(raw: Any) -> LLMResponse:
    """Normalise an SDK response into our provider-neutral shape."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    raw_blocks: list[dict[str, Any]] = []

    for block in raw.content:
        raw_blocks.append(block.model_dump(exclude_none=True))
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))

    usage = Usage(
        input_tokens=getattr(raw.usage, "input_tokens", 0) or 0,
        output_tokens=getattr(raw.usage, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(raw.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(raw.usage, "cache_creation_input_tokens", 0) or 0,
    )

    stop_reason = raw.stop_reason if raw.stop_reason in KNOWN_STOP_REASONS else "end_turn"

    return LLMResponse(
        text="\n".join(text_parts).strip(),
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=stop_reason,
        model=raw.model,
        raw=raw_blocks,
    )


def build_provider(settings: Settings, mock: MockProvider | None = None) -> LLMProvider:
    """Return the provider matching the configured mode.

    Mock is the default. Live mode is opt-in and needs a key, so no code path
    reaches the network by accident.
    """
    if settings.is_live:
        return AnthropicProvider(settings)
    if mock is None:
        raise PermanentProviderError(
            "Mock mode needs a MockProvider with scripted responses. "
            "Pass one explicitly, or set AGENT_MODE=live."
        )
    return mock
