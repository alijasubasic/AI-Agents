"""Runnable demonstration of the lead research agent.

    python -m agents.lead_research.demo

Three companies against a synthetic corpus — one with a thin but contradictory
paper trail, one with almost nothing written about it, and one that does not
appear in the corpus at all. No API key, no network.
"""

from __future__ import annotations

from agents.lead_research.agent import LeadResearchAgent
from agents.lead_research.fixtures import REFERENCE_TODAY
from agents.lead_research.models import FactStatus, ResearchResult
from agents.lead_research.providers import MockSearch
from agents.lead_research.scripted import provider_for
from core.config import Settings
from core.console import configure_stdout

COMPANIES = ("Kestrel Systems", "Halvard Marine", "Vantage Photonics")

_MARK = {
    FactStatus.VERIFIED: "  ok  ",
    FactStatus.STALE: " STALE",
    FactStatus.DISPUTED: " DISP ",
    FactStatus.MISATTRIBUTED: " MISATT",
    FactStatus.UNSOURCED: " UNSRC",
}


def research(company: str, settings: Settings | None = None) -> ResearchResult:
    """Research one company against the fixture corpus."""
    return LeadResearchAgent(
        provider=provider_for(company),
        search=MockSearch(),
        settings=settings or Settings.from_env(),
        today=REFERENCE_TODAY,
    ).research(company)


def research_all(settings: Settings | None = None) -> list[ResearchResult]:
    settings = settings or Settings.from_env()
    return [research(company, settings) for company in COMPANIES]


def _print(result: ResearchResult) -> None:
    print(f"\n{'=' * 76}")
    print(f"{result.company}   ({len(result.sources)} source(s) retrieved)")
    print("=" * 76)
    print(f"  {result.profile.summary}")

    if result.facts:
        print("\n  claims:")
        for fact in result.facts:
            mark = _MARK[fact.status]
            print(f"   [{mark}] {fact.fact.field}: {fact.fact.value}")
            if fact.status is not FactStatus.VERIFIED:
                print(f"            {fact.note}")
    else:
        print("\n  no claims made")

    print(
        f"\n  {len(result.verified)}/{len(result.facts)} verified ({result.confidence_ratio:.0%})"
    )

    if result.profile.open_questions:
        print("  open questions:")
        for question in result.profile.open_questions:
            print(f"    - {question}")


def main() -> None:
    configure_stdout()
    settings = Settings.from_env()
    print("lead-research demo")
    print(f"mode={settings.mode}  model={settings.model}  today={REFERENCE_TODAY}")

    results = research_all(settings)
    for result in results:
        _print(result)

    claims = sum(len(r.facts) for r in results)
    verified = sum(len(r.verified) for r in results)

    print(f"\n{'=' * 76}")
    print(f"{claims} claims across {len(results)} companies | {verified} verified")
    print(
        "Every claim was checked against the document it cited. Two of the\n"
        "Kestrel claims are model failures on purpose - an invented CEO and an\n"
        "unsourced revenue figure - and neither reaches the reader unlabelled."
    )


if __name__ == "__main__":
    main()
