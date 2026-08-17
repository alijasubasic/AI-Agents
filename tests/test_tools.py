"""Tests for the tool registry and schema generation."""

from __future__ import annotations

import pytest

from core.models import ToolCall
from core.tools import ToolRegistry, tool


@tool
def add(a: int, b: int = 0) -> int:
    """Add two integers.

    Args:
        a: The first number.
        b: The second number, defaulting to zero.
    """
    return a + b


@tool
def explode(reason: str) -> str:
    """Always raise, to exercise the error path.

    Args:
        reason: Message to fail with.
    """
    raise RuntimeError(reason)


def test_schema_is_derived_from_type_hints():
    schema = add.input_schema
    assert schema["type"] == "object"
    assert schema["properties"]["a"]["type"] == "integer"
    # `a` has no default, `b` does — only `a` is required.
    assert schema["required"] == ["a"]
    assert schema["additionalProperties"] is False


def test_schema_descriptions_come_from_the_docstring():
    assert add.description == "Add two integers."
    assert add.input_schema["properties"]["b"]["description"] == (
        "The second number, defaulting to zero."
    )


def test_tool_without_docstring_is_rejected():
    def undocumented(x: int) -> int:
        return x

    # The description is what the model uses to decide when to call a tool, so
    # an undocumented tool is a bug rather than a stylistic lapse.
    with pytest.raises(ValueError, match="docstring"):
        tool(undocumented)


def test_registry_executes_a_call():
    registry = ToolRegistry([add])
    result = registry.execute(ToolCall(id="c1", name="add", arguments={"a": 2, "b": 3}))
    assert result.content == "5"
    assert result.is_error is False


def test_unknown_tool_returns_an_error_result_rather_than_raising():
    registry = ToolRegistry([add])
    result = registry.execute(ToolCall(id="c1", name="nope", arguments={}))
    assert result.is_error is True
    assert "nope" in result.content
    # The available tools are named so the model can correct itself.
    assert "add" in result.content


def test_invalid_arguments_are_reported_back_as_an_error_result():
    registry = ToolRegistry([add])
    result = registry.execute(ToolCall(id="c1", name="add", arguments={"a": "not-a-number"}))
    assert result.is_error is True


def test_tool_exceptions_are_captured_not_propagated():
    registry = ToolRegistry([explode])
    result = registry.execute(ToolCall(id="c1", name="explode", arguments={"reason": "boom"}))
    assert result.is_error is True
    assert "boom" in result.content


def test_duplicate_tool_names_are_rejected():
    registry = ToolRegistry([add])
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(add)


def test_non_string_return_values_are_json_encoded():
    @tool
    def as_dict(x: int) -> dict:
        """Return a mapping.

        Args:
            x: Any integer.
        """
        return {"value": x}

    registry = ToolRegistry([as_dict])
    result = registry.execute(ToolCall(id="c1", name="as_dict", arguments={"x": 7}))
    assert result.content == '{"value": 7}'
