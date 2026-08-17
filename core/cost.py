"""Token and dollar accounting for agent runs.

An agent that cannot tell you what it costs is not ready for production, so
cost is a first-class part of every run rather than something bolted on later.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.models import Usage


class ModelPrice(BaseModel):
    """List price in USD per million tokens."""

    input: float
    output: float

    #: Cache reads are billed at ~0.1x the input rate, cache writes at ~1.25x
    #: (for the default 5-minute TTL).
    cache_read_multiplier: float = 0.1
    cache_write_multiplier: float = 1.25


#: Public list prices, USD per million tokens.
#: Keep this table in sync with https://platform.claude.com/docs/en/pricing
PRICING: dict[str, ModelPrice] = {
    "claude-opus-5": ModelPrice(input=5.00, output=25.00),
    "claude-opus-4-8": ModelPrice(input=5.00, output=25.00),
    "claude-sonnet-5": ModelPrice(input=3.00, output=15.00),
    "claude-sonnet-4-6": ModelPrice(input=3.00, output=15.00),
    "claude-haiku-4-5": ModelPrice(input=1.00, output=5.00),
    "claude-fable-5": ModelPrice(input=10.00, output=50.00),
}

#: Used when a model is not in the table. Priced at the most expensive known
#: tier on purpose: an unknown model should over-estimate rather than let a run
#: silently slip past its budget.
FALLBACK_PRICE = ModelPrice(input=10.00, output=50.00)

_PER_MILLION = 1_000_000


def price_for(model: str) -> ModelPrice:
    """Look up a model's list price, falling back to the conservative default."""
    return PRICING.get(model, FALLBACK_PRICE)


def cost_of(usage: Usage, model: str) -> float:
    """Return the USD cost of one model request."""
    price = price_for(model)
    dollars = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_input_tokens * price.input * price.cache_read_multiplier
        + usage.cache_creation_input_tokens * price.input * price.cache_write_multiplier
    )
    return dollars / _PER_MILLION


class CostTracker:
    """Accumulates usage across the steps of a single run."""

    def __init__(self, model: str, budget_usd: float | None = None) -> None:
        self.model = model
        self.budget_usd = budget_usd
        self.usage = Usage()
        self.cost_usd = 0.0

    def add(self, usage: Usage) -> float:
        """Record one request's usage and return the cost of that request."""
        step_cost = cost_of(usage, self.model)
        self.usage = self.usage + usage
        self.cost_usd += step_cost
        return step_cost

    @property
    def over_budget(self) -> bool:
        """True once the run has spent more than its budget allows."""
        return self.budget_usd is not None and self.cost_usd > self.budget_usd

    def summary(self) -> str:
        """A one-line, human-readable summary for demo output."""
        return (
            f"{self.usage.input_tokens:,} in / {self.usage.output_tokens:,} out tokens "
            f"= ${self.cost_usd:.6f}"
        )
