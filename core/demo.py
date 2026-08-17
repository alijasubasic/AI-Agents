"""Runnable demonstration of the core runtime.

    make demo    # or: python -m core.demo

Runs entirely on the mock provider, so it works on a fresh clone with no API
key and no network. Three scenes, each showing one thing the loop must get
right: normal tool use, recovery from a broken tool, and a guardrail firing.
"""

from __future__ import annotations

from core.agent import Agent
from core.config import Settings
from core.llm import MockProvider, text_response, tool_response
from core.models import RunResult
from core.tools import ToolRegistry, tool

# --- Fixture tools ------------------------------------------------------
# Synthetic data only. No customer records ever enter this repository.

_ORDERS = {
    "A-1043": {"sku": "KB-88", "status": "shipped", "customer": "Nordwind GmbH"},
    "A-1044": {"sku": "MS-12", "status": "processing", "customer": "Alpina AG"},
}
_STOCK = {"KB-88": 14, "MS-12": 0}


@tool
def lookup_order(order_id: str) -> dict:
    """Look up an order by its ID.

    Args:
        order_id: The order reference, e.g. "A-1043".
    """
    if order_id not in _ORDERS:
        raise KeyError(f"No order {order_id}")
    return _ORDERS[order_id]


@tool
def check_stock(sku: str) -> str:
    """Report how many units of a SKU are in stock.

    Args:
        sku: The stock keeping unit, e.g. "KB-88".
    """
    return f"{_STOCK.get(sku, 0)} units available"


@tool
def flaky_pricing(sku: str) -> str:
    """Return the current price for a SKU. Deliberately broken, for the demo.

    Args:
        sku: The stock keeping unit.
    """
    raise ConnectionError("pricing-service unreachable (simulated)")


def _registry() -> ToolRegistry:
    return ToolRegistry([lookup_order, check_stock, flaky_pricing])


def _report(title: str, result: RunResult) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")
    for step in result.steps:
        calls = ", ".join(f"{c.name}({c.arguments})" for c in step.tool_calls)
        print(f"  step {step.index}: {calls or 'final answer'}  [{step.duration_ms:.0f} ms]")
        for tool_result in step.tool_results:
            marker = "!!" if tool_result.is_error else "->"
            print(f"      {marker} {tool_result.name}: {tool_result.content[:88]}")
    if result.output:
        print(f"\n  answer: {result.output}")
    print(
        f"\n  {result.step_count} step(s) | "
        f"{result.usage.input_tokens:,} in / {result.usage.output_tokens:,} out tokens | "
        f"${result.cost_usd:.6f} | {result.duration_ms:.0f} ms"
    )
    if result.halted_reason:
        print(f"  halted: {result.halted_reason}")


SYSTEM = (
    "You are a support agent for a hardware distributor. Use the tools to look "
    "up facts before answering. Never guess an order status."
)


def scene_tool_use(settings: Settings) -> RunResult:
    """The happy path: two tool calls, then an answer."""
    provider = MockProvider(
        [
            tool_response("lookup_order", {"order_id": "A-1043"}, call_id="c1"),
            tool_response("check_stock", {"sku": "KB-88"}, call_id="c2"),
            text_response(
                "Order A-1043 for Nordwind GmbH has shipped. The KB-88 is well "
                "stocked, with 14 units still available."
            ),
        ],
        model="claude-opus-5",
    )
    agent = Agent(
        name="support",
        system_prompt=SYSTEM,
        provider=provider,
        tools=_registry(),
        settings=settings,
    )
    return agent.run("Where is order A-1043, and can we reorder that item?")


def scene_tool_failure(settings: Settings) -> RunResult:
    """A tool raises. The failure goes back to the model, which works around it."""
    provider = MockProvider(
        [
            tool_response("flaky_pricing", {"sku": "KB-88"}, call_id="c1"),
            tool_response("check_stock", {"sku": "KB-88"}, call_id="c2"),
            text_response(
                "I could not reach the pricing service, so I cannot quote a price. "
                "I can confirm 14 units of the KB-88 are in stock."
            ),
        ],
        model="claude-opus-5",
    )
    agent = Agent(
        name="support-degraded",
        system_prompt=SYSTEM,
        provider=provider,
        tools=_registry(),
        settings=settings,
    )
    return agent.run("What does the KB-88 cost and is it available?")


def scene_step_limit(settings: Settings) -> RunResult:
    """A model that never stops calling tools. The step ceiling ends the run."""
    capped = settings.model_copy(update={"max_steps": 3})
    provider = MockProvider(
        [tool_response("check_stock", {"sku": "KB-88"}, call_id=f"c{i}") for i in range(6)],
        model="claude-opus-5",
    )
    agent = Agent(
        name="support-runaway",
        system_prompt=SYSTEM,
        provider=provider,
        tools=_registry(),
        settings=capped,
    )
    return agent.run("Keep checking stock forever.")


def main() -> None:
    settings = Settings.from_env()
    print(
        f"ai-agent-portfolio core demo\n"
        f"mode={settings.mode}  model={settings.model}  "
        f"max_steps={settings.max_steps}  budget=${settings.max_cost_usd:.2f}"
    )

    _report("1. Tool use: look up an order, then check stock", scene_tool_use(settings))
    _report("2. Robustness: a tool fails and the agent adapts", scene_tool_failure(settings))
    _report("3. Guardrail: the step limit stops a runaway loop", scene_step_limit(settings))

    print(
        "\nAll three scenes ran against the mock provider — no API key, no network.\n"
        "Set AGENT_MODE=live with an ANTHROPIC_API_KEY to run against Claude."
    )


if __name__ == "__main__":
    main()
