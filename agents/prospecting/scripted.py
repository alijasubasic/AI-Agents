"""Scripted search plans for the demo and the tests.

The planning step is the only model call in this agent, so scripting it makes
the whole pipeline deterministic: same queries, same listings, same merge, same
export, every run. That is what lets the eval suite claim a score means
something.
"""

from __future__ import annotations

from agents.prospecting.models import SearchPlan
from core.llm import MockProvider, text_response

PLANS: dict[str, SearchPlan] = {
    "Dachdecker": SearchPlan(
        queries=[
            "Dachdecker München",
            "Dachdeckerei München",
            "Bedachungen München",
            "Spenglerei München",
        ],
        categories=["Dachdecker", "Spenglerei", "Bedachungen"],
        exclude_terms=["portal", "vergleich", "vermittlung", "handwerkerportal"],
        rationale=(
            "Roofers list themselves under all three trade names in Germany; "
            "portals and lead resellers are excluded because they are not the "
            "business we want to talk to."
        ),
    ),
}


def provider_for(what: str, *, model: str = "claude-opus-5") -> MockProvider:
    """Build a scripted provider for one trade."""
    if what not in PLANS:
        raise KeyError(f"No scripted plan for {what!r}")
    return MockProvider([text_response(PLANS[what].model_dump_json())], model=model)
