"""Shared agent runtime: loop, tools, providers, tracing, cost accounting.

Every agent in `agents/` is built from these pieces. Nothing here depends on a
third-party agent framework.
"""

from core.agent import Agent
from core.config import DEFAULT_MODEL, Settings
from core.cost import CostTracker, cost_of
from core.llm import (
    AnthropicProvider,
    LLMProvider,
    MockProvider,
    build_provider,
    text_response,
    tool_response,
)
from core.models import (
    LLMResponse,
    Message,
    RunResult,
    Step,
    ToolCall,
    ToolResult,
    Usage,
)
from core.tools import Tool, ToolRegistry, tool
from core.tracing import TraceWriter, load_traces

__all__ = [
    "DEFAULT_MODEL",
    "Agent",
    "AnthropicProvider",
    "CostTracker",
    "LLMProvider",
    "LLMResponse",
    "Message",
    "MockProvider",
    "RunResult",
    "Settings",
    "Step",
    "Tool",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
    "TraceWriter",
    "Usage",
    "build_provider",
    "cost_of",
    "load_traces",
    "text_response",
    "tool",
    "tool_response",
]
