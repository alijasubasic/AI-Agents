"""Lead research: retrieve documents, extract facts, label what each is worth.

The model proposes claims with citations. `verification.py` decides which of
them survive contact with the documents they cite.
"""

from agents.lead_research.agent import LeadResearchAgent, build_tools, render_report
from agents.lead_research.models import (
    CompanyProfile,
    Fact,
    FactStatus,
    ResearchResult,
    Source,
    SourceKind,
    VerifiedFact,
)
from agents.lead_research.providers import MockSearch, SearchProvider, WebSearch
from agents.lead_research.verification import (
    STALENESS_MONTHS,
    find_disputes,
    quote_supports,
    verify_all,
    verify_fact,
)

__all__ = [
    "STALENESS_MONTHS",
    "CompanyProfile",
    "Fact",
    "FactStatus",
    "LeadResearchAgent",
    "MockSearch",
    "ResearchResult",
    "SearchProvider",
    "Source",
    "SourceKind",
    "VerifiedFact",
    "WebSearch",
    "build_tools",
    "find_disputes",
    "quote_supports",
    "render_report",
    "verify_all",
    "verify_fact",
]
