"""Prospecting: find the businesses in an area and how to reach them.

Map platforms and directories say which businesses exist. Their own websites say
who runs them and what address they publish. Everything carries the source it
came from, and an address nobody published is labelled a guess rather than
quietly becoming a fact.
"""

from agents.prospecting.agent import (
    LEAD_COLUMNS,
    ProspectingAgent,
    default_plan,
    lead_row,
    render_table,
)
from agents.prospecting.extraction import (
    attribute_email,
    construct_email,
    contacts_from_listing,
    contacts_from_page,
    extract_emails,
    extract_people,
    extract_phones,
    normalise_email,
    normalise_phone,
)
from agents.prospecting.merge import build_leads, group_listings, normalise_name
from agents.prospecting.models import (
    ContactPoint,
    ContactStatus,
    Lead,
    Listing,
    Person,
    Platform,
    ProspectingResult,
    SearchArea,
    SearchPlan,
    WebPage,
)
from agents.prospecting.providers import (
    GooglePlacesProvider,
    HttpPageFetcher,
    MockPages,
    MockPlaces,
    OverpassProvider,
    PageFetcher,
    PlaceProvider,
)

__all__ = [
    "LEAD_COLUMNS",
    "ContactPoint",
    "ContactStatus",
    "GooglePlacesProvider",
    "HttpPageFetcher",
    "Lead",
    "Listing",
    "MockPages",
    "MockPlaces",
    "OverpassProvider",
    "PageFetcher",
    "Person",
    "PlaceProvider",
    "Platform",
    "ProspectingAgent",
    "ProspectingResult",
    "SearchArea",
    "SearchPlan",
    "WebPage",
    "attribute_email",
    "build_leads",
    "construct_email",
    "contacts_from_listing",
    "contacts_from_page",
    "default_plan",
    "extract_emails",
    "extract_people",
    "extract_phones",
    "group_listings",
    "lead_row",
    "normalise_email",
    "normalise_name",
    "normalise_phone",
    "render_table",
]
