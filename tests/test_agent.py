"""Tests for the agent loop — especially the guardrails.

The loop's job is not only to work when everything works. Most of these tests
cover what happens when it does not.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from core.agent import Agent
from core.config import Settings
from core.errors import StructuredOutputError, TransientProviderError
from core.llm import MockProvider, text_response, tool_response
from core.models import LLMResponse, Usage
from core.tools import ToolRegistry, tool


@tool
def echo(value: str) -> str:
    """Return the value unchanged.

    Args:
        value: Anything at all.
    """
    return value


def settings(**overrides) -> Settings:
    """Test settings: tracing off so tests never touch the filesystem."""
    base = {"trace_enabled": False, "max_steps": 5, "timeout_seconds": 30.0}
    return Settings(**{**base, **overrides})


def build(provider: MockProvider, **setting_overrides) -> Agent:
    return Agent(
        name="test-agent",
        system_prompt="You are a test agent.",
        provider=provider,
        tools=ToolRegistry([echo]),
        settings=settings(**setting_overrides),
    )


def test_a_plain_answer_finishes_in_one_step():
    agent = build(MockProvider([text_response("done")]))
    result = agent.run("hello")

    assert result.output == "done"
    assert result.step_count == 1
    assert result.succeeded


def test_tool_call_result_is_fed_back_and_the_run_continues():
    provider = MockProvider(
        [
            tool_response("echo", {"value": "ping"}),
            text_response("the tool said ping"),
        ]
    )
    result = build(provider).run("use the tool")

    assert result.step_count == 2
    assert result.output == "the tool said ping"
    assert result.steps[0].tool_results[0].content == "ping"

    # The second request must carry the tool result back to the model,
    # otherwise the model is answering blind.
    second_request = provider.calls[1]
    assert second_request["messages"][-1]["tool_results"][0]["content"] == "ping"


def test_parallel_tool_results_are_returned_in_a_single_message():
    provider = MockProvider(
        [
            LLMResponse(
                tool_calls=[
                    tool_response("echo", {"value": "a"}, call_id="c1").tool_calls[0],
                    tool_response("echo", {"value": "b"}, call_id="c2").tool_calls[0],
                ],
                stop_reason="tool_use",
            ),
            text_response("both done"),
        ]
    )
    result = build(provider).run("use both")

    assert len(result.steps[0].tool_results) == 2
    # Splitting results across messages trains the model out of parallel calls,
    # so all results for one step must travel together.
    trailing = provider.calls[1]["messages"][-1]
    assert len(trailing["tool_results"]) == 2


def test_step_limit_halts_a_runaway_loop():
    provider = MockProvider([tool_response("echo", {"value": "again"}) for _ in range(10)])
    result = build(provider, max_steps=3).run("loop forever")

    assert result.step_count == 3
    assert result.succeeded is False
    assert "step limit" in result.halted_reason


def test_partial_work_survives_a_halt():
    provider = MockProvider([tool_response("echo", {"value": "kept"}) for _ in range(10)])
    result = build(provider, max_steps=2).run("loop")

    # A halted run still reports what it managed to do — the steps it ran, the
    # tools it called, and what it spent.
    assert result.halted_reason is not None
    assert result.steps[0].tool_results[0].content == "kept"
    assert result.cost_usd > 0


def test_cost_budget_halts_the_run():
    expensive = LLMResponse(
        tool_calls=tool_response("echo", {"value": "x"}).tool_calls,
        stop_reason="tool_use",
        usage=Usage(input_tokens=1_000_000, output_tokens=0),  # $5.00 on Opus 5
    )
    provider = MockProvider([expensive, expensive, expensive], model="claude-opus-5")
    result = build(provider, max_cost_usd=1.0).run("spend money")

    assert result.succeeded is False
    assert "budget" in result.halted_reason
    assert result.step_count == 1


def test_timeout_halts_before_the_step_limit():
    class SlowProvider(MockProvider):
        """Spends real time per call, so the deadline is actually reachable.

        With an instant mock the whole ten-step run finishes inside a
        millisecond and the timeout never gets a chance to fire — which says
        nothing about whether the timeout works.
        """

        def __init__(self):
            super().__init__([tool_response("echo", {"value": "x"}) for _ in range(10)])

        def complete(self, **kwargs):
            time.sleep(0.05)
            return super().complete(**kwargs)

    # Two steps take 0.1s, so the deadline has passed well before step ten.
    result = build(SlowProvider(), timeout_seconds=0.06, max_steps=10).run("slow")

    assert result.succeeded is False
    assert "timeout" in result.halted_reason
    assert result.step_count < 10


def test_cost_and_usage_are_accumulated_across_steps():
    provider = MockProvider(
        [tool_response("echo", {"value": "x"}), text_response("done")],
        model="claude-opus-5",
    )
    result = build(provider).run("go")

    expected_input = sum(s.usage.input_tokens for s in result.steps)
    assert result.usage.input_tokens == expected_input
    assert result.cost_usd == pytest.approx(sum(s.cost_usd for s in result.steps))


def test_transient_provider_errors_are_retried():
    class FlakyProvider(MockProvider):
        def __init__(self):
            super().__init__([text_response("recovered")])
            self.attempts = 0

        def complete(self, **kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise TransientProviderError("429 slow down")
            return super().complete(**kwargs)

    provider = FlakyProvider()
    agent = build(provider)
    agent.settings = settings()
    result = agent.run("hi")

    assert provider.attempts == 3
    assert result.output == "recovered"
    assert result.succeeded


def test_persistent_provider_failure_halts_rather_than_crashing():
    class BrokenProvider(MockProvider):
        def __init__(self):
            super().__init__([text_response("never reached")])

        def complete(self, **kwargs):
            raise TransientProviderError("still down")

    result = build(BrokenProvider()).run("hi")

    # The caller gets a result object, not an exception — a failed run is an
    # outcome the caller has to report, not a crash.
    assert result.succeeded is False
    assert "provider failure" in result.halted_reason


def test_structured_output_is_validated():
    class Answer(BaseModel):
        sentiment: str
        confidence: float

    provider = MockProvider([text_response('{"sentiment": "positive", "confidence": 0.9}')])
    parsed, result = build(provider).run_structured("classify this", Answer)

    assert parsed.sentiment == "positive"
    assert parsed.confidence == 0.9
    assert result.succeeded


def test_structured_output_tolerates_a_code_fence():
    class Answer(BaseModel):
        ok: bool

    provider = MockProvider([text_response('```json\n{"ok": true}\n```')])
    parsed, _ = build(provider).run_structured("go", Answer)
    assert parsed.ok is True


def test_structured_output_rejects_a_mismatched_shape():
    class Answer(BaseModel):
        sentiment: str

    provider = MockProvider([text_response('{"wrong_field": 1}')])
    with pytest.raises(StructuredOutputError):
        build(provider).run_structured("classify", Answer)


def test_system_prompt_reaches_the_provider():
    provider = MockProvider([text_response("ok")])
    build(provider).run("hi")
    assert provider.calls[0]["system"] == "You are a test agent."


def test_tools_are_advertised_to_the_provider():
    provider = MockProvider([text_response("ok")])
    build(provider).run("hi")
    assert provider.calls[0]["tools"] == ["echo"]
