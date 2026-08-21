"""Eval cases for the lead research agent.

All five verification labels get a case, because a labelling system whose
failure paths are never exercised is one nobody should rely on.
"""

from __future__ import annotations

from datetime import date

from agents.lead_research.agent import LeadResearchAgent, render_report
from agents.lead_research.fixtures import REFERENCE_TODAY
from agents.lead_research.models import Fact, FactStatus, Source, SourceKind
from agents.lead_research.providers import MockSearch
from agents.lead_research.scripted import provider_for
from agents.lead_research.verification import quote_supports, verify_all
from core.config import Settings
from evals.models import Expectation, Layer, Score
from evals.registry import case
from evals.scoring import at_most, combine, equals, is_false, is_true, within

AGENT = "lead-research"


def _research(company: str):
    return LeadResearchAgent(
        provider=provider_for(company),
        search=MockSearch(),
        settings=Settings(trace_enabled=False),
        today=REFERENCE_TODAY,
    ).research(company)


def _status(result, field: str) -> FactStatus | None:
    for verified in result.facts:
        if verified.fact.field == field:
            return verified.status
    return None


def _source(text: str, published: date | None = date(2026, 1, 1)) -> Source:
    return Source(
        id="s1",
        url="https://example.test/s1",
        title="Doc",
        kind=SourceKind.COMPANY_SITE,
        published=published,
        text=text,
    )


# --- The five labels ----------------------------------------------------


@case(
    id="research-supported-claim-verifies",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A quote found in a recent cited source is VERIFIED.",
)
def _() -> Score:
    return equals(_status(_research("Kestrel Systems"), "founded"), FactStatus.VERIFIED)


@case(
    id="research-unsourced-claim-is-labelled",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A plausible figure with no citation is kept and marked UNSOURCED.",
)
def _() -> Score:
    result = _research("Kestrel Systems")
    return combine(
        equals(_status(result, "revenue"), FactStatus.UNSOURCED),
        is_true(
            any(f.fact.field == "revenue" for f in result.flagged),
            label="kept rather than deleted",
        ),
    )


@case(
    id="research-invented-citation-is-caught",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A quote attributed to a page that never contained it is MISATTRIBUTED.",
)
def _() -> Score:
    return equals(_status(_research("Kestrel Systems"), "ceo"), FactStatus.MISATTRIBUTED)


@case(
    id="research-old-source-is-stale",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A figure only available from a 2021 article is STALE.",
)
def _() -> Score:
    return equals(_status(_research("Kestrel Systems"), "headcount"), FactStatus.STALE)


@case(
    id="research-contradicting-sources-both-disputed",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Two head offices means both claims are DISPUTED; neither wins.",
)
def _() -> Score:
    result = _research("Kestrel Systems")
    hq = [f for f in result.facts if f.fact.field == "headquarters"]
    return combine(
        equals(len(hq), 2, label="claims"),
        is_true(all(f.status is FactStatus.DISPUTED for f in hq), label="both disputed"),
    )


# --- Scoring and reporting ---------------------------------------------


@case(
    id="research-only-supported-claims-count",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Two of seven Kestrel claims survive verification.",
)
def _() -> Score:
    result = _research("Kestrel Systems")
    return combine(
        equals(len(result.facts), 7, label="claims"),
        equals(len(result.verified), 2, label="verified"),
        within(result.confidence_ratio, 2 / 7, tolerance=0.001, label="ratio"),
    )


@case(
    id="research-report-separates-verified-from-flagged",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="An unsourced figure never appears in the verified section.",
)
def _() -> Score:
    report = render_report(_research("Kestrel Systems"))
    verified_section = report.split("## Not confirmed")[0]
    return combine(
        is_true("## Verified" in report, label="verified section"),
        is_true("## Not confirmed" in report, label="flagged section"),
        is_false("8M ARR" in verified_section, label="unsourced figure leaked upwards"),
    )


@case(
    id="research-thin-corpus-verifies-nothing",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="One two-year-old listing yields no verified facts at all.",
)
def _() -> Score:
    result = _research("Halvard Marine")
    return combine(
        equals(result.verified, [], label="verified"),
        equals(result.confidence_ratio, 0.0, label="ratio"),
    )


@case(
    id="research-absent-company-makes-no-claims",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="With nothing retrieved, the agent claims nothing.",
)
def _() -> Score:
    result = _research("Vantage Photonics")
    return combine(
        equals(result.sources, [], label="sources"),
        equals(result.facts, [], label="claims"),
    )


@case(
    id="research-paraphrase-is-not-a-citation",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Quote matching is verbatim; an approximation fails.",
)
def _() -> Score:
    doc = _source("Acme Ltd is headquartered in Leeds and was founded in 2011.")
    return is_false(quote_supports("Acme is based in Leeds", doc), label="paraphrase accepted")


@case(
    id="research-undated-source-is-not-stale",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Absence of a publication date is not evidence of age.",
)
def _() -> Score:
    doc = _source("Acme Ltd is headquartered in Leeds.", published=None)
    fact = Fact(
        field="headquarters",
        value="Leeds",
        source_id="s1",
        quote="Acme Ltd is headquartered in Leeds.",
    )
    (verified,) = verify_all([fact], [doc], today=date(2026, 3, 5))
    return equals(verified.status, FactStatus.VERIFIED)


@case(
    id="research-citing-an-unretrieved-source-fails",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A source id that was never fetched cannot support a claim.",
)
def _() -> Score:
    fact = Fact(field="headquarters", value="Leeds", source_id="s-nope", quote="anything")
    (verified,) = verify_all([fact], [_source("text")], today=date(2026, 3, 5))
    return equals(verified.status, FactStatus.MISATTRIBUTED)


# --- Known gaps ---------------------------------------------------------


@case(
    id="research-misreading-a-real-quote-passes",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A correct quote supporting a wrong conclusion is scored VERIFIED.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Verification checks that the sentence exists, not that the value "
        "follows from it. 'Founded in 2017' cited as a headcount of 2017 would "
        "pass. Catching this needs entailment, not substring matching."
    ),
)
def _() -> Score:
    doc = _source("Acme Ltd was founded in 2011.")
    fact = Fact(
        field="headcount",
        value="2011",
        source_id="s1",
        quote="Acme Ltd was founded in 2011.",
    )
    (verified,) = verify_all([fact], [doc], today=date(2026, 3, 5))
    return is_false(verified.status is FactStatus.VERIFIED, label="wrong inference rejected")


@case(
    id="research-source-quality-is-recorded-not-used",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A directory scrape and a registry filing are weighted identically.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "SourceKind distinguishes them and nothing consumes it. A self-reported "
        "headcount on a company's own site is not evidence of the same quality "
        "as a filing, and the score does not know that."
    ),
)
def _() -> Score:
    result = _research("Kestrel Systems")
    kinds = {f.source.kind for f in result.facts if f.source}
    return is_true(len(kinds) == 1, label="source quality influences the outcome")


@case(
    id="research-staleness-is-one-number-for-every-field",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A founding date is aged out on the same schedule as a headcount.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "STALENESS_MONTHS is global. A company's founding year does not become "
        "less true after eighteen months, so the flag fires on facts it should "
        "not, which trains people to ignore it."
    ),
)
def _() -> Score:
    doc = _source("Acme Ltd was founded in 2011.", published=date(2020, 1, 1))
    fact = Fact(
        field="founded", value="2011", source_id="s1", quote="Acme Ltd was founded in 2011."
    )
    (verified,) = verify_all([fact], [doc], today=date(2026, 3, 5))
    return equals(verified.status, FactStatus.VERIFIED, label="founding date not aged out")


@case(
    id="research-caps-claims-per-company",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Nothing limits how many claims a profile may assert.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "A model that produces thirty weakly-sourced facts scores the same "
        "per-claim as one that produces five well-sourced ones, and the "
        "confidence ratio is the only signal that anything went wrong."
    ),
)
def _() -> Score:
    return at_most(len(_research("Kestrel Systems").facts), 5, label="claims per profile")
