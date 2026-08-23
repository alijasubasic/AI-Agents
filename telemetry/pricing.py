"""Turning the model ids in a transcript into money.

Transcripts record the wire model id — `claude-opus-4-1-20250805` — and the
price table in `core/cost.py` is keyed by the names this repository uses. This
maps one onto the other, and stays deliberately small: the family is decided by
the first word that matches, because Anthropic's naming has been stable on that
point across every id shape so far and guessing more than that would be
guessing.

**The correction worth calling out.** The dashboard this idea is borrowed from
costs a session as `input * rate + output * rate` and ignores the cache fields
entirely. On a long agent session most input tokens are cache reads, so that
undercounts by a wide margin — a session of mine that it would price at a few
cents is several times that. `core.cost.cost_of` already bills cache reads at
0.1x and cache writes at 1.25x, so the fix here is simply to use it.
"""

from __future__ import annotations

from core.cost import FALLBACK_PRICE, PRICING, ModelPrice
from core.models import Usage

#: Family name -> the entry in `core.cost.PRICING` that prices it.
_FAMILY_PRICE: dict[str, str] = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5",
}

#: Ids that are not a billable model. `<synthetic>` appears on records Claude
#: Code generates itself; counting it as an unknown model would price local
#: bookkeeping at the most expensive tier.
NON_MODELS = frozenset({"<synthetic>", ""})


def model_family(model: str | None) -> str:
    """The family a wire model id belongs to.

    Returns "unknown" rather than guessing a family, so an id nobody has seen
    before shows up on the dashboard as unknown instead of being quietly filed
    under whichever family sorts first.
    """
    if not model or model in NON_MODELS:
        return "unknown"
    lowered = model.lower()
    for family in _FAMILY_PRICE:
        if family in lowered:
            return family
    return "unknown"


def price_of(model: str | None) -> ModelPrice:
    """The price table entry for a wire model id.

    An unrecognised family gets `FALLBACK_PRICE`, which is the most expensive
    tier on purpose — the same reasoning as `core.cost.price_for`. A cost
    estimate that errs low is one that lets a bill surprise you.
    """
    key = _FAMILY_PRICE.get(model_family(model))
    return PRICING[key] if key else FALLBACK_PRICE


def cost_of_usage(usage: Usage, model: str | None) -> float:
    """USD for one request's usage, cache tokens included."""
    price = price_of(model)
    dollars = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_input_tokens * price.input * price.cache_read_multiplier
        + usage.cache_creation_input_tokens * price.input * price.cache_write_multiplier
    )
    return dollars / 1_000_000
