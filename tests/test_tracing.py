"""Tests for run tracing."""

from __future__ import annotations

from core.agent import Agent
from core.config import Settings
from core.llm import MockProvider, text_response, tool_response
from core.models import RunResult
from core.tools import ToolRegistry, tool
from core.tracing import TraceWriter, load_traces


@tool
def noop(value: str) -> str:
    """Return the value unchanged.

    Args:
        value: Anything.
    """
    return value


def test_a_run_writes_one_trace_file(tmp_path):
    agent = Agent(
        name="traced",
        system_prompt="test",
        provider=MockProvider([tool_response("noop", {"value": "x"}), text_response("done")]),
        tools=ToolRegistry([noop]),
        settings=Settings(trace_enabled=True, trace_dir=tmp_path),
    )
    agent.run("go")

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_the_trace_round_trips_with_every_step(tmp_path):
    agent = Agent(
        name="traced",
        system_prompt="test",
        provider=MockProvider([tool_response("noop", {"value": "x"}), text_response("done")]),
        tools=ToolRegistry([noop]),
        settings=Settings(trace_enabled=True, trace_dir=tmp_path),
    )
    agent.run("go")

    (loaded,) = load_traces(tmp_path)
    assert loaded.agent == "traced"
    assert loaded.output == "done"
    assert len(loaded.steps) == 2
    assert loaded.steps[0].tool_calls[0].name == "noop"
    assert loaded.cost_usd > 0


def test_tracing_can_be_disabled(tmp_path):
    writer = TraceWriter(tmp_path, enabled=False)
    assert writer.write(RunResult(agent="a", model="m", mode="mock")) is None
    assert list(tmp_path.glob("*.json")) == []


def test_loading_from_a_missing_directory_is_empty(tmp_path):
    assert load_traces(tmp_path / "does-not-exist") == []


def test_corrupt_traces_are_skipped(tmp_path):
    writer = TraceWriter(tmp_path)
    writer.write(RunResult(agent="good", model="m", mode="mock"))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    # One bad file from an interrupted run must not hide the others.
    loaded = load_traces(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].agent == "good"
