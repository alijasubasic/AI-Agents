"""Tests for token and dollar accounting."""

from __future__ import annotations

import pytest

from core.cost import FALLBACK_PRICE, CostTracker, cost_of, price_for
from core.models import Usage


def test_cost_matches_the_published_list_price():
    # Claude Opus 5: $5 per million input tokens, $25 per million output.
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_of(usage, "claude-opus-5") == 30.0


def test_cache_reads_are_cheaper_than_fresh_input():
    fresh = cost_of(Usage(input_tokens=10_000), "claude-opus-5")
    cached = cost_of(Usage(cache_read_input_tokens=10_000), "claude-opus-5")
    assert cached < fresh
    # approx, not ==: 0.05 * 0.1 is 0.005000000000000001 in binary floating point.
    assert cached == pytest.approx(fresh * 0.1)


def test_cache_writes_cost_more_than_fresh_input():
    fresh = cost_of(Usage(input_tokens=10_000), "claude-opus-5")
    written = cost_of(Usage(cache_creation_input_tokens=10_000), "claude-opus-5")
    assert written == pytest.approx(fresh * 1.25)


def test_unknown_models_fall_back_to_the_conservative_price():
    # An unknown model must over-estimate: a run should never slip past its
    # budget because we had no price on file.
    assert price_for("some-future-model") == FALLBACK_PRICE
    most_expensive = max(p.output for p in [price_for("claude-opus-5"), FALLBACK_PRICE])
    assert FALLBACK_PRICE.output == most_expensive


def test_tracker_accumulates_across_steps():
    tracker = CostTracker("claude-opus-5")
    tracker.add(Usage(input_tokens=1000, output_tokens=500))
    tracker.add(Usage(input_tokens=2000, output_tokens=250))

    assert tracker.usage.input_tokens == 3000
    assert tracker.usage.output_tokens == 750
    assert tracker.cost_usd == cost_of(Usage(input_tokens=3000, output_tokens=750), "claude-opus-5")


def test_tracker_reports_going_over_budget():
    tracker = CostTracker("claude-opus-5", budget_usd=0.01)
    assert tracker.over_budget is False

    tracker.add(Usage(input_tokens=1_000_000, output_tokens=0))  # $5.00
    assert tracker.over_budget is True


def test_tracker_without_a_budget_is_never_over():
    tracker = CostTracker("claude-opus-5")
    tracker.add(Usage(input_tokens=10_000_000, output_tokens=10_000_000))
    assert tracker.over_budget is False
