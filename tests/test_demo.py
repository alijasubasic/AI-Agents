"""The demo is a promise in the README, so it is covered by a test.

`make demo` must keep working on a clean machine with no API key. A test is
the only thing that stops that promise from quietly rotting.
"""

from __future__ import annotations

from core import demo
from core.config import Settings


def _settings() -> Settings:
    return Settings(trace_enabled=False)


def test_tool_use_scene_answers_after_two_tool_calls():
    result = demo.scene_tool_use(_settings())

    assert result.succeeded
    assert result.step_count == 3
    assert "Nordwind" in result.output
    assert [c.name for s in result.steps for c in s.tool_calls] == [
        "lookup_order",
        "check_stock",
    ]


def test_failure_scene_surfaces_the_tool_error_and_still_answers():
    result = demo.scene_tool_failure(_settings())

    assert result.succeeded
    failures = [r for s in result.steps for r in s.tool_results if r.is_error]
    assert len(failures) == 1
    assert "pricing-service unreachable" in failures[0].content
    # The agent must still produce an answer despite the broken tool.
    assert result.output


def test_step_limit_scene_halts():
    result = demo.scene_step_limit(_settings())

    assert result.succeeded is False
    assert "step limit" in result.halted_reason
    assert result.step_count == 3


def test_demo_main_runs_without_a_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("TRACE_ENABLED", "false")

    demo.main()

    output = capsys.readouterr().out
    assert "no API key, no network" in output
