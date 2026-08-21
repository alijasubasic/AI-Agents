"""Data models for lead research.

Research output is the easiest thing in this repository to get quietly wrong. A
model asked about a company will produce a confident, well-formatted profile
whether or not it read anything, because a plausible headcount is as easy to
generate as a real one. Nothing about the answer distinguishes the two.

So the unit of output here is not a profile — it is a **fact with a citation**,
and a separate verification pass decides what each one is worth. The model
proposes; `verification.py` labels.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class SourceKind(StrEnum):
    """Where a document came from. Not all sources are worth the same."""

    COMPANY_SITE = "company_site"
    PRESS_RELEASE = "press_release"
    NEWS = "news"
    REGISTRY = "registry"
    DIRECTORY = "directory"
    SOCIAL = "social"


class Source(BaseModel):
    """One retrieved document."""

    id: str
    url: str
    title: str
    kind: SourceKind
    published: date | None = None
    text: str = ""

    @property
    def label(self) -> str:
        return f"{self.title} ({self.url})"


class FactStatus(StrEnum):
    """What verification concluded about one claim.

    Only `VERIFIED` means "we found this written down in a document we
    retrieved". Everything else is a caveat the reader must see.
    """

    #: The cited source exists and contains the supporting quote.
    VERIFIED = "verified"
    #: No source was cited. The model may well be right; we have no evidence.
    UNSOURCED = "unsourced"
    #: A source was cited but does not contain the quote attributed to it.
    MISATTRIBUTED = "misattributed"
    #: Verified, but the source is old enough that the value may have moved.
    STALE = "stale"
    #: Another source gives a different value for the same field.
    DISPUTED = "disputed"


class Fact(BaseModel):
    """One claim the model wants to make.

    Field descriptions are prompt text — this schema is what the model is shown.
    """

    field: str = Field(
        description=(
            "What this fact is about, as a short snake_case key: headquarters, "
            "headcount, founded, funding, sector, ceo."
        )
    )
    value: str = Field(description="The value, as briefly as it can be stated.")
    source_id: str | None = Field(
        default=None,
        description=(
            "The id of the source this came from, exactly as given in the search "
            "results. Null if no retrieved source supports it. Do not cite a "
            "source you did not read, and do not cite one because it seems "
            "likely to contain the fact."
        ),
    )
    quote: str = Field(
        default="",
        description=(
            "The exact sentence from that source supporting this value, copied "
            "verbatim. Empty when there is no source."
        ),
    )


class VerifiedFact(BaseModel):
    """A fact after the verification pass."""

    fact: Fact
    status: FactStatus
    note: str = ""
    source: Source | None = None

    @property
    def is_usable(self) -> bool:
        """Whether this can be stated without a caveat attached."""
        return self.status is FactStatus.VERIFIED

    def render(self) -> str:
        """One line for a report, caveat included where one is needed."""
        marker = "" if self.is_usable else f"  [{self.status.value.upper()}]"
        citation = f"  — {self.source.url}" if self.source else ""
        return f"{self.fact.field}: {self.fact.value}{citation}{marker}"


class CompanyProfile(BaseModel):
    """What the model assembled about a company."""

    legal_name: str = Field(description="The company's name as the sources give it.")
    website: str = Field(default="", description="Primary website, or empty if not found.")
    summary: str = Field(
        description=(
            "Two or three sentences on what the company does, drawn only from "
            "the sources you retrieved."
        )
    )
    facts: list[Fact] = Field(
        default_factory=list, description="Structured claims, each with its citation."
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description=(
            "Things a salesperson would want to know that the sources did not "
            "answer. Naming a gap is more useful than filling it with a guess."
        ),
    )


class ResearchResult(BaseModel):
    """The profile plus what verification made of it."""

    company: str
    profile: CompanyProfile
    facts: list[VerifiedFact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)

    cost_usd: float = 0.0
    duration_ms: float = 0.0
    halted_reason: str | None = None

    @property
    def verified(self) -> list[VerifiedFact]:
        return [f for f in self.facts if f.is_usable]

    @property
    def flagged(self) -> list[VerifiedFact]:
        return [f for f in self.facts if not f.is_usable]

    @property
    def confidence_ratio(self) -> float:
        """Share of claims that survived verification. 0.0 when nothing was claimed."""
        return len(self.verified) / len(self.facts) if self.facts else 0.0
