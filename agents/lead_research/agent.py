"""The lead research agent.

Research is the easiest task here to fake convincingly. A model asked about a
company will produce a tidy profile whether or not it read anything, and the
output looks identical either way.

The shape of this agent follows from that:

    1. The model may only use what the tools returned. It is told so, and the
       tools are the only place source ids come from.
    2. Every claim must carry a source id and a verbatim quote.
    3. `verification.py` then checks each quote against the document it was
       attributed to, and labels what it finds.

Step 3 is the part worth looking at. Nothing is trusted because it was asserted
confidently — a claim is verified because the sentence supporting it was found
in a document that was actually retrieved.
"""

from __future__ import annotations

import time
from datetime import date

from agents.lead_research.models import (
    CompanyProfile,
    FactStatus,
    ResearchResult,
    Source,
)
from agents.lead_research.providers import SearchProvider
from agents.lead_research.verification import STALENESS_MONTHS, verify_all
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider
from core.tools import Tool, ToolRegistry

SYSTEM_PROMPT = """\
You research companies for a sales team.

Use the tools to retrieve documents, then assemble a profile from what they
actually say.

Rules:

- Use search_company before anything else. You have no knowledge of these
  companies beyond what the tools return.
- Every fact carries the source id it came from and the exact sentence from that
  source, copied verbatim. The sentence is checked against the document, so a
  paraphrase will be rejected.
- If nothing you retrieved supports a fact, set source_id to null rather than
  citing a source that seems likely to contain it. An unsourced fact is
  acceptable and will be labelled as such. A wrongly attributed one is not.
- When sources disagree, report both values with their own citations. Do not
  pick a winner; that is the reader's call, and they need to know there was a
  disagreement at all.
- Put what the sources did not answer in open_questions. Naming a gap is more
  useful to a salesperson than filling it with a plausible guess.
"""


def build_tools(search: SearchProvider) -> ToolRegistry:
    """Build the retrieval tools, closing over the provider in use."""

    def search_company(company: str) -> str:
        """Retrieve documents about a company.

        Args:
            company: The company name to research, e.g. "Kestrel Systems".
        """
        sources = search.search(company)
        if not sources:
            return (
                f"No documents found for {company!r}. Report this rather than "
                f"answering from memory."
            )
        return "\n\n".join(_render_source(source) for source in sources)

    def fetch_source(source_id: str) -> str:
        """Retrieve the full text of one document by its source id.

        Args:
            source_id: The id from a search result, e.g. "src-01".
        """
        source = search.fetch(source_id)
        if source is None:
            return f"No document with id {source_id!r}."
        return _render_source(source)

    return ToolRegistry([Tool(search_company), Tool(fetch_source)])


def _render_source(source: Source) -> str:
    published = source.published.isoformat() if source.published else "date unknown"
    return (
        f"[{source.id}] {source.title}\n"
        f"url: {source.url}\n"
        f"kind: {source.kind.value}  published: {published}\n"
        f"---\n{source.text}"
    )


class LeadResearchAgent:
    """Researches a company and labels every claim by how well it is supported."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        search: SearchProvider,
        settings: Settings | None = None,
        today: date | None = None,
    ) -> None:
        self.search = search
        self.today = today or date.today()
        self._agent = Agent(
            name="lead-research",
            system_prompt=SYSTEM_PROMPT,
            provider=provider,
            tools=build_tools(search),
            settings=settings,
        )

    def research(self, company: str) -> ResearchResult:
        """Research one company and verify everything the model claimed."""
        started = time.monotonic()

        profile, run = self._agent.run_structured(
            f"Research {company} and produce a profile.", CompanyProfile
        )

        # Verification runs against what retrieval actually returned, not
        # against the ids the model mentioned. A claim citing a source that was
        # never retrieved is exactly the failure worth catching.
        sources = self.search.search(company)
        verified = verify_all(profile.facts, sources, today=self.today)

        return ResearchResult(
            company=company,
            profile=profile,
            facts=verified,
            sources=sources,
            cost_usd=run.cost_usd,
            duration_ms=(time.monotonic() - started) * 1000,
            halted_reason=run.halted_reason,
        )


_STATUS_NOTE = {
    FactStatus.UNSOURCED: "no supporting document was retrieved",
    FactStatus.MISATTRIBUTED: "the cited document does not contain the quote",
    FactStatus.DISPUTED: "sources disagree",
    FactStatus.STALE: f"the source is more than {STALENESS_MONTHS} months old",
}


def render_report(result: ResearchResult) -> str:
    """Render the research as Markdown. Deterministic, no model call.

    Verified facts and flagged ones are kept in separate sections. Mixing them
    with a footnote would let a reader skim past the caveats, which defeats the
    point of having them.
    """
    lines = [
        f"# {result.profile.legal_name or result.company}",
        "",
        result.profile.summary,
        "",
        f"*{len(result.verified)} of {len(result.facts)} claims verified against "
        f"{len(result.sources)} retrieved source(s).*",
        "",
        "## Verified",
        "",
    ]

    if result.verified:
        lines += [
            f"- **{f.fact.field}:** {f.fact.value}  \n"
            f"  <sub>{f.source.label if f.source else ''}</sub>"
            for f in result.verified
        ]
    else:
        lines.append("_Nothing could be verified against a retrieved source._")

    if result.flagged:
        lines += ["", "## Not confirmed", "", "Do not repeat these to a prospect as fact.", ""]
        for f in result.flagged:
            reason = f.note or _STATUS_NOTE.get(f.status, "")
            source = f"  \n  <sub>{f.source.label}</sub>" if f.source else ""
            lines.append(
                f"- **{f.fact.field}:** {f.fact.value} — `{f.status.value}`, {reason}{source}"
            )

    if result.profile.open_questions:
        lines += ["", "## Open questions", ""]
        lines += [f"- {question}" for question in result.profile.open_questions]

    lines += ["", "## Sources", ""]
    lines += [
        f"- `{s.id}` [{s.title}]({s.url}) — {s.kind.value}, "
        f"{s.published.isoformat() if s.published else 'date unknown'}"
        for s in result.sources
    ] or ["_None retrieved._"]

    return "\n".join(lines)
