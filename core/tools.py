"""Tool registry.

A tool is an ordinary Python function. The JSON schema the model sees is
derived from the function's type hints and docstring, so the schema can never
drift away from the implementation — there is only one source of truth.

    @tool
    def get_weather(city: str, unit: str = "celsius") -> str:
        '''Look up the current weather for a city.

        Args:
            city: City name, e.g. "Berlin".
            unit: Either "celsius" or "fahrenheit".
        '''
        ...
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel, Field, ValidationError, create_model

from core.errors import ToolExecutionError, ToolNotFound, ToolValidationError
from core.models import ToolCall, ToolResult

_ARGS_HEADER = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", re.IGNORECASE)
_ARG_LINE = re.compile(r"^\s*(\*{0,2}\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)$")


def _split_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into a summary and per-argument descriptions.

    Anything after the ``Args:`` header is treated as argument documentation
    until a blank line followed by a new section, which is good enough for the
    docstring styles used in this repository.
    """
    if not doc:
        return "", {}

    lines = inspect.cleandoc(doc).splitlines()
    summary: list[str] = []
    args: dict[str, str] = {}
    current: str | None = None
    in_args = False

    for line in lines:
        if _ARGS_HEADER.match(line):
            in_args = True
            continue

        if not in_args:
            summary.append(line)
            continue

        # A non-indented, non-empty line ends the Args block (e.g. "Returns:").
        if line.strip() and not line.startswith((" ", "\t")):
            break

        match = _ARG_LINE.match(line)
        if match:
            current = match.group(1).lstrip("*")
            args[current] = match.group(2).strip()
        elif current and line.strip():
            args[current] += " " + line.strip()

    return "\n".join(summary).strip(), args


def _schema_for(fn: Callable[..., Any]) -> tuple[type[BaseModel], dict[str, Any]]:
    """Build a pydantic model and JSON schema describing ``fn``'s parameters."""
    signature = inspect.signature(fn)
    hints = get_type_hints(fn)
    _, arg_docs = _split_docstring(fn.__doc__)

    fields: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        if name in {"self", "cls"} or param.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue

        annotation = hints.get(name, str)
        description = arg_docs.get(name)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, Field(default, description=description))

    model = create_model(f"{fn.__name__.title().replace('_', '')}Args", **fields)
    schema = model.model_json_schema()
    schema.pop("title", None)
    # The API expects a plain object schema; strict tool use additionally
    # requires additionalProperties to be false.
    schema.setdefault("type", "object")
    schema["additionalProperties"] = False
    return model, schema


class Tool:
    """A callable paired with the schema the model uses to invoke it."""

    def __init__(self, fn: Callable[..., Any], *, name: str | None = None) -> None:
        summary, _ = _split_docstring(fn.__doc__)
        if not summary:
            raise ValueError(
                f"Tool {fn.__name__!r} needs a docstring — the model relies on it "
                f"to decide when to call the tool."
            )

        self.fn = fn
        self.name = name or fn.__name__
        self.description = summary
        self.args_model, self.input_schema = _schema_for(fn)

    def to_api_format(self) -> dict[str, Any]:
        """Render the tool definition in the shape the Anthropic API expects."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def run(self, arguments: dict[str, Any]) -> str:
        """Validate arguments, call the function, and return a string result.

        Validation errors and execution errors are raised as distinct types so
        the caller can decide which ones are worth reporting back to the model.
        """
        try:
            validated = self.args_model(**arguments)
        except ValidationError as exc:
            raise ToolValidationError(self.name, exc.json(indent=None)) from exc

        try:
            result = self.fn(**validated.model_dump())
        except Exception as exc:  # noqa: BLE001 - tools are user code; surface anything
            raise ToolExecutionError(self.name, exc) from exc

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


class ToolRegistry:
    """A named collection of tools handed to an agent."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool_obj in tools or []:
            self.register(tool_obj)

    def register(self, tool_obj: Tool) -> Tool:
        if tool_obj.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool_obj.name!r}")
        self._tools[tool_obj.name] = tool_obj
        return tool_obj

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFound(name, sorted(self._tools))
        return self._tools[name]

    def to_api_format(self) -> list[dict[str, Any]]:
        return [t.to_api_format() for t in self._tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        """Run one tool call, converting any failure into an error result.

        Failures are deliberately returned rather than raised: a model that
        invents a tool name or passes a bad argument should get a chance to
        correct itself, which it can only do if the failure reaches it as a
        tool result.
        """
        try:
            output = self.get(call.name).run(call.arguments)
        except (ToolNotFound, ToolValidationError, ToolExecutionError) as exc:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=str(exc),
                is_error=True,
            )
        return ToolResult(tool_call_id=call.id, name=call.name, content=output)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())


def tool(fn: Callable[..., Any]) -> Tool:
    """Decorator turning a function into a :class:`Tool`."""
    return Tool(fn)
