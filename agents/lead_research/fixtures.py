"""A synthetic corpus of retrievable documents.

Invented companies, invented documents. The corpus is built to contain the
problems real research runs into rather than a clean set of agreeing pages:

* two sources that place the head office in different cities
* a headcount figure that is only available from a five-year-old article
* a company site that never names the chief executive, so a model tempted to
  supply one has nowhere honest to cite
* a second company with almost nothing written about it at all

Dates line up with the other agents: "today" is Thursday 5 March 2026.
"""

from __future__ import annotations

from datetime import date

from agents.lead_research.models import Source, SourceKind

REFERENCE_TODAY = date(2026, 3, 5)


CORPUS: dict[str, list[Source]] = {
    "Kestrel Systems": [
        Source(
            id="src-01",
            url="https://kestrel-systems.example/about",
            title="About — Kestrel Systems",
            kind=SourceKind.COMPANY_SITE,
            published=date(2026, 1, 15),
            text=(
                "Kestrel Systems designs and manufactures industrial input devices "
                "for logistics and warehouse operations. Founded in 2017, the "
                "company is headquartered in New York, NY. Our products are used by "
                "distribution centres across North America and Europe. The "
                "leadership team brings experience from industrial automation and "
                "enterprise hardware."
            ),
        ),
        Source(
            id="src-02",
            url="https://logisticsweekly.example/kestrel-expands-scanner-line",
            title="Kestrel expands warehouse scanner line",
            kind=SourceKind.NEWS,
            published=date(2021, 6, 2),
            text=(
                "Kestrel Systems, a New York startup with around 20 employees, has "
                "expanded its warehouse scanner line. The company said demand from "
                "third-party logistics providers drove the decision."
            ),
        ),
        Source(
            id="src-03",
            url="https://bizdirectory.example/company/kestrel-systems",
            title="Kestrel Systems — company listing",
            kind=SourceKind.DIRECTORY,
            published=date(2025, 11, 20),
            text=(
                "Kestrel Systems - Industrial Equipment. Head office: Boston, MA. "
                "Employees: 11-50. Listing last reviewed November 2025."
            ),
        ),
        Source(
            id="src-04",
            url="https://kestrel-systems.example/press/series-a",
            title="Kestrel Systems closes Series A",
            kind=SourceKind.PRESS_RELEASE,
            published=date(2025, 9, 10),
            text=(
                "Kestrel Systems today announced the close of a $12 million Series A "
                "financing led by Ardent Ventures. The round will fund expansion of "
                "its European sales operation."
            ),
        ),
    ],
    "Halvard Marine": [
        Source(
            id="src-11",
            url="https://bizdirectory.example/company/halvard-marine",
            title="Halvard Marine — company listing",
            kind=SourceKind.DIRECTORY,
            published=date(2024, 4, 8),
            text=(
                "Halvard Marine - Shipbuilding and repair. Bergen, Norway. "
                "Listing last reviewed April 2024."
            ),
        ),
    ],
}


def sources_for(company: str) -> list[Source]:
    """Every document the corpus holds about a company. Empty if unknown."""
    return list(CORPUS.get(company, []))
