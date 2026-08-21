"""Scripted model responses for the research demo and tests.

The Kestrel profile is written to trip **every** verification outcome, because
a labelling system whose failure paths have never run is a labelling system
nobody should rely on:

    founded, funding     VERIFIED       quote found in the cited document
    headcount            STALE          only available from a 2021 article
    headquarters (x2)    DISPUTED       the site says New York, a directory says Boston
    ceo                  MISATTRIBUTED  a name the company site never mentions
    revenue              UNSOURCED      a plausible figure with nothing behind it

The ceo and revenue entries are deliberate model failures. They are what a real
model does on a thin corpus, and the point of this agent is that neither one
reaches the reader unlabelled.
"""

from __future__ import annotations

from agents.lead_research.models import CompanyProfile, Fact
from core.llm import MockProvider, text_response, tool_response

PROFILES: dict[str, CompanyProfile] = {
    "Kestrel Systems": CompanyProfile(
        legal_name="Kestrel Systems",
        website="https://kestrel-systems.example",
        summary=(
            "Kestrel Systems designs and manufactures industrial input devices for "
            "logistics and warehouse operations, sold to distribution centres in "
            "North America and Europe. It raised a Series A in September 2025 to "
            "expand its European sales operation."
        ),
        facts=[
            Fact(
                field="founded",
                value="2017",
                source_id="src-01",
                quote=("Founded in 2017, the company is headquartered in New York, NY."),
            ),
            Fact(
                field="headquarters",
                value="New York, NY",
                source_id="src-01",
                quote=("Founded in 2017, the company is headquartered in New York, NY."),
            ),
            Fact(
                field="headquarters",
                value="Boston, MA",
                source_id="src-03",
                quote="Head office: Boston, MA.",
            ),
            Fact(
                field="headcount",
                value="around 20",
                source_id="src-02",
                quote=(
                    "Kestrel Systems, a New York startup with around 20 employees, "
                    "has expanded its warehouse scanner line."
                ),
            ),
            Fact(
                field="funding",
                value="$12M Series A led by Ardent Ventures",
                source_id="src-04",
                quote=(
                    "Kestrel Systems today announced the close of a $12 million "
                    "Series A financing led by Ardent Ventures."
                ),
            ),
            # The company site never names a chief executive. This citation
            # points at it anyway.
            Fact(
                field="ceo",
                value="Marisol Trent",
                source_id="src-01",
                quote="Kestrel Systems is led by chief executive Marisol Trent.",
            ),
            # A plausible number with nothing behind it at all.
            Fact(field="revenue", value="approximately $8M ARR"),
        ],
        open_questions=[
            "Current headcount — the only figure available is from 2021",
            "Which head office is current: New York or Boston",
            "Who leads the company",
            "Whether they already buy comparable hardware elsewhere",
        ],
    ),
    "Halvard Marine": CompanyProfile(
        legal_name="Halvard Marine",
        website="",
        summary=(
            "Halvard Marine is a shipbuilding and repair business in Bergen, "
            "Norway. Only a single directory listing was retrieved, so almost "
            "nothing can be established about the company's current state."
        ),
        facts=[
            Fact(
                field="headquarters",
                value="Bergen, Norway",
                source_id="src-11",
                quote="Halvard Marine - Shipbuilding and repair. Bergen, Norway.",
            ),
            Fact(
                field="sector",
                value="Shipbuilding and repair",
                source_id="src-11",
                quote="Halvard Marine - Shipbuilding and repair. Bergen, Norway.",
            ),
        ],
        open_questions=[
            "Company size and headcount",
            "Whether the business is still trading",
            "Who to contact",
            "Any recent yard activity or contracts",
        ],
    ),
    "Vantage Photonics": CompanyProfile(
        legal_name="Vantage Photonics",
        website="",
        summary=(
            "No documents were retrieved for this company. Nothing can be "
            "reported about it from this search."
        ),
        facts=[],
        open_questions=[
            "Everything — no source was found. Confirm the company name and "
            "whether it trades under a different one.",
        ],
    ),
}


def provider_for(company: str, *, model: str = "claude-opus-5") -> MockProvider:
    """Build a scripted provider for one research scenario."""
    if company not in PROFILES:
        raise KeyError(f"No scripted profile for {company!r}")
    return MockProvider(
        [
            tool_response("search_company", {"company": company}, call_id="search-1"),
            text_response(PROFILES[company].model_dump_json()),
        ],
        model=model,
    )
