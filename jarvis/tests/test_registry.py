"""Tests that keep the fleet registry honest.

A hand-maintained list of agents drifts the moment somebody renames a module,
and it drifts silently. These are the checks that turn `FLEET` from
documentation into something that can be *wrong* — and therefore caught.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from jarvis.registry import FLEET, AgentCard, packages_on_disk, reachable_names

ROOT = Path(__file__).resolve().parents[2]


def test_every_registered_agent_has_a_package():
    missing = [card.name for card in FLEET if not (ROOT / "agents" / card.package).is_dir()]
    assert missing == []


def test_no_agent_package_is_missing_from_the_registry():
    """The check that actually catches drift.

    The other direction — registry entries pointing at real packages — is easy
    to keep true by accident. This one fails when somebody adds an agent and
    forgets the card, which is the mistake that actually happens.
    """
    registered = {card.package for card in FLEET}
    assert packages_on_disk(ROOT) == registered


def test_every_agent_has_a_readme():
    missing = [card.name for card in FLEET if not (ROOT / card.readme).is_file()]
    assert missing == []


@pytest.mark.parametrize("card", FLEET, ids=lambda card: card.name)
def test_every_demo_module_imports(card: AgentCard):
    # A dashboard that offers to run a demo which does not exist is worse than
    # one that offers nothing.
    assert importlib.import_module(card.demo) is not None


def test_names_and_packages_are_unique():
    assert len({card.name for card in FLEET}) == len(FLEET)
    assert len({card.package for card in FLEET}) == len(FLEET)


def test_reachable_agents_match_the_live_console():
    """The chat panel says which agents take free text. It has to be true."""
    from console.live import KNOWN_ATTENDEES  # noqa: F401  (import proves the module loads)
    from jarvis.registry import BY_NAME

    for name in reachable_names():
        assert name in BY_NAME
    assert set(reachable_names()) == {"lead-research", "knowledge-base", "calendar-booking"}


def test_initials_are_derived_not_stored():
    assert (
        AgentCard(name="lead-research", title="x", package="p", colour="#fff", blurb="").initials
        == "LR"
    )
    # A single-word name falls back to its first two letters.
    assert (
        AgentCard(name="supervisor", title="x", package="p", colour="#fff", blurb="").initials
        == "SU"
    )


def test_every_colour_is_a_hex_value():
    # The page writes these straight into a CSS custom property.
    for card in FLEET:
        assert card.colour.startswith("#")
        assert len(card.colour) in (4, 7)
        int(card.colour[1:], 16)
