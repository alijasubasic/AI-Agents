"""Exception hierarchy for the agent runtime.

Every failure mode an agent can hit gets its own type, so callers can decide
what is retryable and what is fatal instead of matching on error strings.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for every error raised by this runtime."""


# --- Control-flow limits ------------------------------------------------


class StepLimitExceeded(AgentError):
    """The agent used all allowed reasoning steps without finishing.

    This is a normal outcome, not a crash: an agent that loops forever is a
    far worse failure than one that stops and reports partial progress.
    """

    def __init__(self, steps: int) -> None:
        super().__init__(f"Agent stopped after reaching the {steps}-step limit")
        self.steps = steps


class TimeoutExceeded(AgentError):
    """The agent exceeded its wall-clock budget."""

    def __init__(self, timeout_s: float) -> None:
        super().__init__(f"Agent stopped after exceeding {timeout_s:.1f}s time budget")
        self.timeout_s = timeout_s


class BudgetExceeded(AgentError):
    """The agent exceeded its cost budget for a single run."""

    def __init__(self, spent_usd: float, limit_usd: float) -> None:
        super().__init__(f"Run cost ${spent_usd:.4f} exceeded budget of ${limit_usd:.4f}")
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd


# --- Tool layer ---------------------------------------------------------


class ToolError(AgentError):
    """Base class for tool problems."""


class ToolNotFound(ToolError):
    """The model asked for a tool that is not in the registry.

    Models do occasionally invent tool names. We surface this back into the
    conversation as a tool result rather than crashing the run, so the model
    gets a chance to correct itself.
    """

    def __init__(self, name: str, available: list[str]) -> None:
        known = ", ".join(available) or "none"
        super().__init__(f"Unknown tool {name!r}. Available tools: {known}")
        self.name = name
        self.available = available


class ToolExecutionError(ToolError):
    """A tool was found but raised while running."""

    def __init__(self, name: str, cause: Exception) -> None:
        super().__init__(f"Tool {name!r} failed: {type(cause).__name__}: {cause}")
        self.name = name
        self.cause = cause


class ToolValidationError(ToolError):
    """The arguments the model supplied did not match the tool schema."""

    def __init__(self, name: str, detail: str) -> None:
        super().__init__(f"Invalid arguments for tool {name!r}: {detail}")
        self.name = name
        self.detail = detail


# --- Provider layer -----------------------------------------------------


class ProviderError(AgentError):
    """Base class for LLM provider failures."""


class TransientProviderError(ProviderError):
    """A failure that is worth retrying (rate limit, 5xx, connection reset)."""


class PermanentProviderError(ProviderError):
    """A failure that retrying cannot fix (bad request, auth, missing key)."""


# --- Output layer -------------------------------------------------------


class StructuredOutputError(AgentError):
    """The model's final answer did not validate against the expected schema."""

    def __init__(self, model_name: str, detail: str) -> None:
        super().__init__(f"Could not parse response into {model_name}: {detail}")
        self.model_name = model_name
        self.detail = detail
