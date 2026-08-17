"""The agent loop.

This is the piece most projects delegate to a framework. It is written by hand
here because the loop *is* the interesting part: what stops it, what it does
when a tool explodes, and what it costs.

The loop is deliberately boring:

    while under all limits:
        ask the model
        if it asked for tools -> run them, feed results back, continue
        otherwise -> that is the answer, stop

Everything else is guardrails: a step ceiling, a wall-clock deadline, a dollar
budget, and retries with backoff for transient provider failures.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from core.config import Settings
from core.cost import CostTracker
from core.errors import (
    PermanentProviderError,
    StructuredOutputError,
    TransientProviderError,
)
from core.llm import LLMProvider
from core.models import LLMResponse, Message, RunResult, Step
from core.tools import ToolRegistry
from core.tracing import TraceWriter

T = TypeVar("T", bound=BaseModel)

#: Retry schedule for transient provider errors. Short by design — an agent
#: that hangs for two minutes retrying is worse than one that fails clearly.
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 0.5


class Agent:
    """A single agent: a system prompt, a tool set, and a loop around a model."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        provider: LLMProvider,
        tools: ToolRegistry | None = None,
        settings: Settings | None = None,
        tracer: TraceWriter | None = None,
        max_tokens: int = 8192,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.provider = provider
        self.tools = tools or ToolRegistry()
        self.settings = settings or Settings.from_env()
        self.max_tokens = max_tokens
        self.tracer = tracer or TraceWriter(
            self.settings.trace_dir, enabled=self.settings.trace_enabled
        )

    # -- public API ------------------------------------------------------

    def run(self, user_input: str, *, history: Sequence[Message] | None = None) -> RunResult:
        """Run the agent to completion and return a full record of what happened.

        This never raises for an expected stop condition. Hitting the step
        limit, the timeout, or the budget is an *outcome*, not a crash — the
        caller gets a populated :class:`RunResult` with ``halted_reason`` set,
        including whatever partial work was done. Only programmer errors
        (a broken provider, a malformed config) propagate.
        """
        started = time.monotonic()
        deadline = started + self.settings.timeout_seconds
        tracker = CostTracker(self.provider.model, budget_usd=self.settings.max_cost_usd)

        messages: list[Message] = list(history or [])
        messages.append(Message(role="user", text=user_input))

        result = RunResult(
            agent=self.name,
            model=self.provider.model,
            mode=self.settings.mode,
        )

        for index in range(self.settings.max_steps):
            if time.monotonic() > deadline:
                result.halted_reason = (
                    f"timeout after {self.settings.timeout_seconds:.0f}s "
                    f"({index} step(s) completed)"
                )
                break

            step_started = time.monotonic()
            try:
                response = self._complete_with_retry(messages)
            except (TransientProviderError, PermanentProviderError) as exc:
                result.halted_reason = f"provider failure: {exc}"
                break

            step_cost = tracker.add(response.usage)
            step = Step(
                index=index,
                duration_ms=(time.monotonic() - step_started) * 1000,
                text=response.text,
                tool_calls=response.tool_calls,
                usage=response.usage,
                cost_usd=step_cost,
                stop_reason=response.stop_reason,
            )

            messages.append(
                Message(
                    role="assistant",
                    text=response.text,
                    tool_calls=response.tool_calls,
                    raw=response.raw,
                )
            )

            # No tool calls means the model is answering rather than working.
            if not response.wants_tools:
                step.duration_ms = (time.monotonic() - step_started) * 1000
                result.steps.append(step)
                result.output = response.text
                break

            # Run every requested tool, then return all results in one message.
            # Splitting them across messages trains the model out of making
            # parallel calls, so they always travel together.
            tool_results = [self.tools.execute(call) for call in response.tool_calls]
            step.tool_results = tool_results
            step.duration_ms = (time.monotonic() - step_started) * 1000
            result.steps.append(step)

            messages.append(Message(role="user", tool_results=tool_results))

            if tracker.over_budget:
                result.halted_reason = (
                    f"cost budget exceeded: ${tracker.cost_usd:.4f} of "
                    f"${self.settings.max_cost_usd:.4f}"
                )
                break
        else:
            result.halted_reason = f"step limit reached ({self.settings.max_steps} steps)"

        result.usage = tracker.usage
        result.cost_usd = tracker.cost_usd
        result.duration_ms = (time.monotonic() - started) * 1000
        self.tracer.write(result)
        return result

    def run_structured(self, user_input: str, output_model: type[T]) -> tuple[T, RunResult]:
        """Run the agent and validate its final answer against a pydantic model.

        Structured output is enforced by schema, not by asking the model nicely
        and hoping. If the answer does not validate, that is an error the caller
        sees rather than a silently mangled object.
        """
        schema = json.dumps(output_model.model_json_schema(), indent=2)
        agent = Agent(
            name=self.name,
            system_prompt=(
                f"{self.system_prompt}\n\n"
                f"Respond with a single JSON object matching this schema. "
                f"Output nothing else — no prose, no code fences.\n\n{schema}"
            ),
            provider=self.provider,
            tools=self.tools,
            settings=self.settings,
            tracer=self.tracer,
            max_tokens=self.max_tokens,
        )

        result = agent.run(user_input)
        try:
            parsed = output_model.model_validate_json(_strip_code_fence(result.output))
        except ValidationError as exc:
            raise StructuredOutputError(output_model.__name__, str(exc)) from exc
        return parsed, result

    # -- internals -------------------------------------------------------

    def _complete_with_retry(self, messages: Sequence[Message]) -> LLMResponse:
        """Call the provider, retrying transient failures with jittered backoff."""
        last_error: TransientProviderError | None = None

        for attempt in range(MAX_RETRIES):
            try:
                return self.provider.complete(
                    system=self.system_prompt,
                    messages=messages,
                    tools=self.tools.to_api_format(),
                    max_tokens=self.max_tokens,
                )
            except TransientProviderError as exc:
                last_error = exc
                if attempt == MAX_RETRIES - 1:
                    break
                # Full jitter: without it, concurrent agents retry in lockstep
                # and re-create the overload they are backing off from.
                delay = BASE_BACKOFF_SECONDS * (2**attempt)
                time.sleep(random.uniform(0, delay))  # noqa: S311 - not cryptographic

        assert last_error is not None  # only reachable after a transient failure
        raise last_error


def _strip_code_fence(text: str) -> str:
    """Remove a surrounding ```json fence if the model added one anyway."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped
