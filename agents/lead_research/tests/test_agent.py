"""Tests for the research agent end to end, on scripted model responses."""

from __future__ import annotations

import pytest

from agents.lead_research.agent import LeadResearchAgent, build_tools, render_report
from agents.lead_research.fixtures import REFERENCE_TODAY
from agents.lead_research.models import FactStatus
from agents.lead_research.providers import MockSearch
from agents.lead_research.scripted import PROFILES, provider_for
from core.config import Settings


def settings() -> Settings:
    return Settings(trace_enabled=False)


def build(company: str) -> tuple[LeadResearchAgent, MockSearch]:
    search = MockSearch()
    agent = LeadResearchAgent(
        provider=provider_for(company),
        search=search,
        settings=settings(),
        today=REFERENCE_TODAY,
    )
    return agent, search


def statuses(result) -> dict[str, FactStatus]:
    """Field name to status, for the fields that appear once."""
    return {f.fact.field: f.status for f in result.facts if f.fact.field != "headquarters"}


# --- Retrieval ----------------------------------------------------------


def test_the_agent_retrieves_before_answering():
    agent, search = build("Kestrel Systems")
    agent.research("Kestrel Systems")

    assert "Kestrel Systems" in search.queries


def test_retrieved_sources_are_attached_to_the_result():
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    assert len(result.sources) == 4
    assert {s.id for s in result.sources} == {"src-01", "src-02", "src-03", "src-04"}


# --- Verification outcomes ---------------------------------------------


def test_a_supported_recent_claim_is_verified():
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    assert statuses(result)["founded"] is FactStatus.VERIFIED
    assert statuses(result)["funding"] is FactStatus.VERIFIED


def test_an_invented_citation_is_caught():
    # The scripted profile attributes a CEO name to the company site, which
    # never mentions one.
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    assert statuses(result)["ceo"] is FactStatus.MISATTRIBUTED


def test_an_unsourced_claim_is_labelled_not_dropped():
    # The revenue figure has nothing behind it. It is kept and marked, because
    # silently deleting it would hide that the model produced it at all.
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    assert statuses(result)["revenue"] is FactStatus.UNSOURCED
    assert any(f.fact.field == "revenue" for f in result.flagged)


def test_a_figure_only_available_from_an_old_source_is_stale():
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    assert statuses(result)["headcount"] is FactStatus.STALE


def test_contradicting_sources_are_both_reported():
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    hq = [f for f in result.facts if f.fact.field == "headquarters"]
    assert len(hq) == 2
    assert all(f.status is FactStatus.DISPUTED for f in hq)
    assert {f.fact.value for f in hq} == {"New York, NY", "Boston, MA"}


def test_only_supported_claims_count_as_verified():
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    assert len(result.facts) == 7
    assert len(result.verified) == 2
    assert len(result.flagged) == 5
    assert result.confidence_ratio == pytest.approx(2 / 7)


# --- Thin and missing corpora ------------------------------------------


def test_a_company_with_one_old_source_verifies_nothing():
    agent, _ = build("Halvard Marine")
    result = agent.research("Halvard Marine")

    assert result.verified == []
    assert result.confidence_ratio == 0.0
    assert all(f.status is FactStatus.STALE for f in result.facts)


def test_a_company_with_no_sources_makes_no_claims():
    agent, search = build("Vantage Photonics")
    result = agent.research("Vantage Photonics")

    assert result.sources == []
    assert result.facts == []
    assert result.confidence_ratio == 0.0
    assert search.queries.count("Vantage Photonics") >= 1


def test_the_empty_corpus_tool_response_warns_against_answering_from_memory():
    registry = build_tools(MockSearch())
    output = registry.get("search_company").run({"company": "Nobody Ltd"})

    assert "No documents found" in output
    assert "from memory" in output


# --- Tools --------------------------------------------------------------


def test_the_search_tool_exposes_source_ids_and_text():
    registry = build_tools(MockSearch())
    output = registry.get("search_company").run({"company": "Kestrel Systems"})

    assert "[src-01]" in output
    assert "published: 2026-01-15" in output
    assert "headquartered in New York" in output


def test_the_fetch_tool_returns_one_document():
    registry = build_tools(MockSearch())
    output = registry.get("fetch_source").run({"source_id": "src-04"})

    assert "Series A" in output


def test_fetching_an_unknown_id_says_so():
    registry = build_tools(MockSearch())
    assert "No document" in registry.get("fetch_source").run({"source_id": "src-99"})


def test_both_tools_are_advertised():
    names = {t["name"] for t in build_tools(MockSearch()).to_api_format()}
    assert names == {"search_company", "fetch_source"}


# --- Report -------------------------------------------------------------


def test_the_report_separates_verified_from_flagged():
    agent, _ = build("Kestrel Systems")
    report = render_report(agent.research("Kestrel Systems"))

    assert "## Verified" in report
    assert "## Not confirmed" in report
    # A reader skimming the verified section must not meet an unsourced figure.
    verified_section = report.split("## Not confirmed")[0]
    assert "8M ARR" not in verified_section


def test_the_report_warns_against_repeating_unconfirmed_claims():
    agent, _ = build("Kestrel Systems")
    report = render_report(agent.research("Kestrel Systems"))

    assert "Do not repeat these to a prospect as fact." in report


def test_the_report_lists_every_source_with_its_date():
    agent, _ = build("Kestrel Systems")
    report = render_report(agent.research("Kestrel Systems"))

    for source_id in ("src-01", "src-02", "src-03", "src-04"):
        assert source_id in report
    assert "2021-06-02" in report


def test_the_report_handles_a_profile_with_nothing_verified():
    agent, _ = build("Vantage Photonics")
    report = render_report(agent.research("Vantage Photonics"))

    assert "Nothing could be verified" in report
    assert "_None retrieved._" in report


def test_the_report_is_deterministic():
    agent, _ = build("Kestrel Systems")
    result = agent.research("Kestrel Systems")

    assert render_report(result) == render_report(result)


def test_open_questions_reach_the_report():
    agent, _ = build("Kestrel Systems")
    report = render_report(agent.research("Kestrel Systems"))

    assert "## Open questions" in report
    assert "Who leads the company" in report


# --- Scenarios ----------------------------------------------------------


def test_every_scripted_profile_can_be_researched():
    for company in PROFILES:
        agent, _ = build(company)
        assert agent.research(company).company == company

    with pytest.raises(KeyError):
        provider_for("No Such Company")
