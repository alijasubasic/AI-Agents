"""The prospecting agent: which businesses exist in an area, and how to reach them.

The division of labour here is the whole design, and it is the opposite of what
most "AI lead finder" products do:

    the model      decides how to phrase the search
    the platforms  decide which businesses exist
    the regexes    decide what their contact details are
    the statuses   decide which of those may be written to

A model never sees a company and never produces a contact detail. It cannot,
because every field on a :class:`Lead` is copied from a provider response or a
retrieved page, and the provenance travels with it. That is what makes the
output usable: a phone number in the export can be traced to the listing it came
from, and an address that cannot be traced anywhere is labelled
`CONSTRUCTED` and refused by everything downstream.

The one place a guess is generated at all is `construct_email`, and it exists so
that the refusal can be demonstrated rather than merely claimed.
"""

from __future__ import annotations

import time

from agents.prospecting.extraction import construct_email
from agents.prospecting.merge import build_leads
from agents.prospecting.models import (
    ContactStatus,
    Lead,
    Listing,
    ProspectingResult,
    SearchArea,
    SearchPlan,
    WebPage,
    domain_of,
)
from agents.prospecting.providers import PageFetcher, PlaceProvider
from core.agent import Agent
from core.config import Settings
from core.llm import LLMProvider

SYSTEM_PROMPT = """\
You plan how to search for local businesses on map and directory platforms.

You are given an area and a trade. Produce the search phrases a person familiar
with that market would type.

Rules:

- Write the queries in the language of the target country. A German trade has a
  German name, and the platforms index it under that name, not its translation.
- Include the obvious synonyms and the neighbouring trade names a small business
  might list itself under. Two to five queries; more than that returns the same
  businesses again and costs money each time.
- Never name a specific company. You do not know which companies exist in this
  area, and inventing one produces a search that finds nothing or, worse,
  something.
- Use exclude_terms for the kinds of hits that are not the business you want:
  comparison portals, lead-selling middlemen, wholesalers, franchise head
  offices. These are filtered out of the results by name, so give the words that
  actually appear in such a listing's name.
"""

AREA_TEMPLATE = """\
Plan the search.

Trade: {what}
Place: {where}
Radius: {radius_km:.0f} km
Country: {country}
Wanted: up to {limit} businesses
"""


def default_plan(area: SearchArea) -> SearchPlan:
    """The plan used when no model is available.

    Not a fallback in the apologetic sense: a plain "trade in place" query is
    what most searches reduce to anyway, and having it means the pipeline runs
    with no provider at all — which is how the tests exercise everything below
    the planning step.
    """
    return SearchPlan(
        queries=[f"{area.what} {area.where}", f"{area.what} in {area.where}"],
        categories=[area.what],
        exclude_terms=["portal", "vergleich", "vermittlung", "verzeichnis"],
        rationale="Deterministic plan: trade plus place, no model involved.",
    )


class ProspectingAgent:
    """Finds businesses in an area across several platforms and merges them."""

    def __init__(
        self,
        *,
        places: list[PlaceProvider],
        pages: PageFetcher | None = None,
        provider: LLMProvider | None = None,
        settings: Settings | None = None,
        max_sites: int = 25,
    ) -> None:
        if not places:
            raise ValueError("ProspectingAgent needs at least one place provider")

        self.places = places
        self.pages = pages
        self.max_sites = max_sites
        self.settings = settings or Settings.from_env()
        self._agent = (
            Agent(
                name="prospecting",
                system_prompt=SYSTEM_PROMPT,
                provider=provider,
                settings=self.settings,
            )
            if provider is not None
            else None
        )

    # -- public API ------------------------------------------------------

    def plan(self, area: SearchArea) -> tuple[SearchPlan, float, str | None]:
        """Ask the model how to search. Returns the plan, its cost, and any halt."""
        if self._agent is None:
            return default_plan(area), 0.0, None

        plan, run = self._agent.run_structured(
            AREA_TEMPLATE.format(
                what=area.what,
                where=area.where,
                radius_km=area.radius_km,
                country=area.country,
                limit=area.limit,
            ),
            SearchPlan,
        )
        # A plan with no queries would search for nothing at all and report an
        # empty area, which looks exactly like a place with no roofers in it.
        if not plan.queries:
            plan.queries = default_plan(area).queries
        return plan, run.cost_usd, run.halted_reason

    def find(self, area: SearchArea, *, plan: SearchPlan | None = None) -> ProspectingResult:
        """Search every platform, merge the results, and read the websites."""
        started = time.monotonic()

        cost, halted = 0.0, None
        if plan is None:
            plan, cost, halted = self.plan(area)

        listings = self._search_platforms(area, plan)
        kept = [listing for listing in listings if not _excluded(listing, plan.exclude_terms)]

        pages_by_domain = self._read_websites(kept)
        leads, duplicates = build_leads(kept, pages_by_domain)

        for lead in leads:
            _add_constructed_guess(lead)

        leads.sort(key=_ranking)

        return ProspectingResult(
            area=area,
            plan=plan,
            leads=leads[: area.limit],
            listings_seen=len(listings),
            duplicates_merged=duplicates,
            pages_read=sum(len(pages) for pages in pages_by_domain.values()),
            cost_usd=cost,
            duration_ms=(time.monotonic() - started) * 1000,
            halted_reason=halted,
        )

    # -- internals -------------------------------------------------------

    def _search_platforms(self, area: SearchArea, plan: SearchPlan) -> list[Listing]:
        """Run every query against every platform, keeping each listing once.

        The same business comes back from several queries on the same platform.
        That is not a duplicate to be merged later — it is literally the same
        record, so it is dropped here by platform id, before merging has to
        reason about it.
        """
        seen: set[tuple[str, str]] = set()
        listings: list[Listing] = []

        for place in self.places:
            for query in plan.queries:
                for listing in place.search(area, query):
                    key = (listing.platform.value, listing.platform_id or listing.name)
                    if key in seen:
                        continue
                    seen.add(key)
                    listings.append(listing)

        return listings

    def _read_websites(self, listings: list[Listing]) -> dict[str, list[WebPage]]:
        """Read each distinct company website once.

        This is the step that produces email addresses. No map platform returns
        one; the business publishes it on its own imprint page, because it is
        required to.
        """
        if self.pages is None:
            return {}

        by_domain: dict[str, str] = {}
        for listing in listings:
            if listing.website:
                by_domain.setdefault(domain_of(listing.website), listing.website)

        pages: dict[str, list[WebPage]] = {}
        for domain, website in list(by_domain.items())[: self.max_sites]:
            found = self.pages.fetch(website)
            if found:
                pages[domain] = found

        return pages


def _excluded(listing: Listing, exclude_terms: list[str]) -> bool:
    """Whether a listing is the wrong kind of business.

    Matched against the name and the categories only. Matching the whole record
    would exclude a roofer whose street happens to be called Portalweg.
    """
    haystack = f"{listing.name} {' '.join(listing.categories)}".lower()
    return any(term.strip().lower() in haystack for term in exclude_terms if term.strip())


def _add_constructed_guess(lead: Lead) -> None:
    """Where a lead has a named person and no address, record the likely one.

    Recorded, labelled, and never sent to. A salesperson looking at the export
    can try it by hand and take responsibility for that; the system will not do
    it on their behalf, because a wrong guess reaches a stranger who never
    published anything.
    """
    if lead.best_email() is not None or not lead.website:
        return

    person = lead.primary_person()
    if person is None:
        return

    guess = construct_email(person, domain_of(lead.website))
    if guess is None:
        return

    lead.contacts.append(guess)
    lead.notes.append(
        f"no published address; {guess.value} is a pattern guess and is not used for sending"
    )


def _ranking(lead: Lead) -> tuple[float, float, float, str]:
    """Most useful first: contactable, then well corroborated, then complete."""
    return (
        0 if lead.is_contactable else 1,
        -lead.confidence,
        -lead.completeness,
        lead.name.lower(),
    )


# --- Rendering ----------------------------------------------------------

_STATUS_MARK = {
    ContactStatus.CONFIRMED: "bestätigt",
    ContactStatus.REPORTED: "gemeldet",
    ContactStatus.CONSTRUCTED: "geraten",
    ContactStatus.INVALID: "ungültig",
}

#: Columns of the lead export, in the order a salesperson reads them.
LEAD_COLUMNS = (
    "Firma",
    "Ansprechpartner",
    "Position",
    "E-Mail",
    "E-Mail-Status",
    "Telefon",
    "Telefon-Status",
    "Website",
    "Adresse",
    "Plattformen",
    "Konfidenz",
    "Fehlt",
    "Quelle",
)


def lead_row(lead: Lead) -> list[str]:
    """One lead as a row of strings, for CSV or a table.

    The status columns are not decoration. A row whose email says `geraten` is
    a row nobody may paste into a mail client, and the export says so on the
    same line rather than in a legend at the bottom.
    """
    person = lead.primary_person()
    email = lead.best_email() or next(iter(lead.emails), None)
    phone = lead.best_phone()

    return [
        lead.name,
        person.name if person else "",
        person.role if person else "",
        email.value if email else "",
        _STATUS_MARK[email.status] if email else "",
        phone.value if phone else "",
        _STATUS_MARK[phone.status] if phone else "",
        lead.website,
        lead.address,
        ", ".join(platform.label for platform in lead.platforms),
        f"{lead.confidence:.2f}",
        ", ".join(lead.missing),
        (email or phone).source_url if (email or phone) else "",
    ]


def render_table(result: ProspectingResult) -> str:
    """The leads as a plain-text table, for the demo and the CLI."""
    header = f"{'Firma':<34} {'Ansprechpartner':<20} {'E-Mail':<38} {'Telefon':<16} {'Status':<10}"
    lines = [header, "-" * len(header)]

    for lead in result.leads:
        person = lead.primary_person()
        email = lead.best_email() or next(iter(lead.emails), None)
        phone = lead.best_phone()
        lines.append(
            f"{lead.name[:33]:<34} "
            f"{(person.name if person else '—')[:19]:<20} "
            f"{(email.value if email else '—')[:37]:<38} "
            f"{(phone.value if phone else '—'):<16} "
            f"{(_STATUS_MARK[email.status] if email else '—'):<10}"
        )

    return "\n".join(lines)
