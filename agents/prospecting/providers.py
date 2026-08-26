"""The platforms, behind two interfaces.

`PlaceProvider` finds businesses in an area. `PageFetcher` reads what a business
publishes about itself. Both have a fixture-backed mock, which is the default
everywhere, and a live implementation that talks to the real service.

The live implementations are written against the documented APIs and use only
the standard library, so nothing new appears in `pyproject.toml`. They are **not
covered by tests** — running them needs a key, a network and someone else's
rate limit — and are marked as such, the same way `agents/lead_research`
marks its live search.

Two things are worth knowing before switching them on:

* **Google's Places API returns no email addresses.** It never has. Any product
  that offers you "emails from Google Maps" got them somewhere else, usually by
  scraping the website behind the listing — which is exactly what
  :class:`HttpPageFetcher` does here, openly, and only for pages whose
  `robots.txt` allows it.
* **Scraping the Maps interface itself is a licence breach**, so nothing here
  does. The Places API is the supported route and the only one implemented.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import UTC, datetime
from typing import Any, Protocol

from agents.prospecting.fixtures import ALL_LISTINGS, PAGES
from agents.prospecting.models import Listing, Platform, SearchArea, WebPage, domain_of

USER_AGENT = "ai-agent-portfolio/0.1 (+https://github.com/alijasubasic/AI-Agents)"

#: Pages worth reading on a company site, in the order they are worth reading.
#: A German imprint is legally obliged to carry the responsible person's name,
#: which makes it the single most valuable page on any small business's site.
CONTACT_PATH_HINTS = (
    "impressum",
    "kontakt",
    "contact",
    "team",
    "ueber-uns",
    "über-uns",
    "about",
)

_PAGE_KIND_HINTS = (
    ("impressum", "impressum"),
    ("imprint", "impressum"),
    ("kontakt", "kontakt"),
    ("contact", "kontakt"),
    ("team", "team"),
    ("ueber", "team"),
    ("about", "team"),
)


class PlaceProvider(Protocol):
    """Finding businesses in an area."""

    platform: Platform

    def search(self, area: SearchArea, query: str) -> list[Listing]: ...


class PageFetcher(Protocol):
    """Reading what a business publishes on its own site."""

    def fetch(self, website: str) -> list[WebPage]: ...


# --- Mocks --------------------------------------------------------------


class MockPlaces:
    """One platform's fixture listings, filtered the way that platform filters.

    The match is deliberately crude — a substring test over the name and
    categories — because the mock's job is to be *predictable*, not to be a
    convincing imitation of a search engine. Every eval score in this repository
    depends on this returning the same rows every time.
    """

    def __init__(self, platform: Platform, listings: list[Listing] | None = None) -> None:
        self.platform = platform
        self._listings = list(listings if listings is not None else ALL_LISTINGS.get(platform, []))
        #: Every query the agent ran, so tests can assert it actually searched.
        self.queries: list[str] = []

    def search(self, area: SearchArea, query: str) -> list[Listing]:
        self.queries.append(query)
        terms = [word.lower() for word in re.split(r"\W+", query) if len(word) > 3]

        matched = [
            listing
            for listing in self._listings
            if not terms
            or any(
                term in haystack
                for term in terms
                for haystack in (
                    listing.name.lower(),
                    " ".join(listing.categories).lower(),
                    listing.city.lower(),
                )
            )
        ]
        return matched[: area.limit]


class MockPages:
    """The fixture websites, keyed by domain."""

    def __init__(self, pages: dict[str, list[WebPage]] | None = None) -> None:
        self._pages = dict(pages if pages is not None else PAGES)
        self.fetched: list[str] = []

    def fetch(self, website: str) -> list[WebPage]:
        self.fetched.append(website)
        return list(self._pages.get(domain_of(website), []))


# --- Google Places (live) ----------------------------------------------


class GooglePlacesProvider:
    """Text Search against the Places API (New).

    NOT COVERED BY TESTS. Needs `GOOGLE_MAPS_API_KEY` and bills per request.

    The field mask is not optional decoration: Places bills by the fields you
    ask for, and asking for everything on a 200-result sweep is how a lead run
    costs more than the leads are worth. Only the fields this pipeline actually
    uses are requested.

    `phone` comes back from the API. `email` does not, and no field mask will
    produce one — that gap is what :class:`HttpPageFetcher` fills.
    """

    platform = Platform.GOOGLE_MAPS

    ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
    FIELD_MASK = ",".join(
        (
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.addressComponents",
            "places.location",
            "places.internationalPhoneNumber",
            "places.nationalPhoneNumber",
            "places.websiteUri",
            "places.primaryTypeDisplayName",
            "places.types",
            "places.rating",
            "places.userRatingCount",
            "places.googleMapsUri",
        )
    )

    def __init__(
        self,
        api_key: str,
        *,
        language: str = "de",
        region: str = "DE",
        center: tuple[float, float] | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        if not api_key:
            raise ValueError("GooglePlacesProvider needs an API key (GOOGLE_MAPS_API_KEY).")
        self._api_key = api_key
        self._language = language
        self._region = region
        self._center = center
        self._timeout_s = timeout_s

    def search(self, area: SearchArea, query: str) -> list[Listing]:  # pragma: no cover - network
        payload: dict[str, Any] = {
            "textQuery": query,
            "languageCode": self._language,
            "regionCode": area.country or self._region,
            # The API caps a single page at 20; the caller's limit is applied
            # after merging, where duplicates have already been removed.
            "maxResultCount": min(area.limit, 20),
        }
        if self._center is not None:
            latitude, longitude = self._center
            payload["locationBias"] = {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": min(area.radius_km * 1000, 50_000),
                }
            }

        request = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": self.FIELD_MASK,
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))

        return [self._to_listing(place) for place in body.get("places", [])]

    def _to_listing(self, place: dict[str, Any]) -> Listing:  # pragma: no cover - network
        components = {
            component_type: component.get("longText", "")
            for component in place.get("addressComponents", [])
            for component_type in component.get("types", [])
        }
        location = place.get("location", {})
        street = " ".join(
            part
            for part in (components.get("route", ""), components.get("street_number", ""))
            if part
        ).strip()

        return Listing(
            platform=self.platform,
            platform_id=place.get("id", ""),
            name=place.get("displayName", {}).get("text", ""),
            street=street or place.get("formattedAddress", "").split(",")[0],
            postal_code=components.get("postal_code", ""),
            city=components.get("locality", "") or components.get("postal_town", ""),
            country=components.get("country", "DE"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            phone_raw=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", ""),
            website=place.get("websiteUri", ""),
            categories=[
                category
                for category in (
                    place.get("primaryTypeDisplayName", {}).get("text", ""),
                    *place.get("types", []),
                )
                if category
            ],
            rating=place.get("rating"),
            review_count=place.get("userRatingCount"),
            source_url=place.get("googleMapsUri", ""),
            retrieved_at=datetime.now(UTC),
        )


# --- OpenStreetMap (live) ----------------------------------------------

#: German trade names mapped to the OSM tags that describe them. Short on
#: purpose: an incomplete table falls back to a name search, while a wrong entry
#: silently returns the wrong trade.
OSM_TAG_HINTS: dict[str, tuple[str, ...]] = {
    "dachdecker": ('["craft"="roofer"]',),
    "elektriker": ('["craft"="electrician"]', '["shop"="electrical"]'),
    "installateur": ('["craft"="plumber"]',),
    "sanitär": ('["craft"="plumber"]',),
    "heizung": ('["craft"="hvac"]', '["craft"="plumber"]'),
    "maler": ('["craft"="painter"]',),
    "schreiner": ('["craft"="carpenter"]',),
    "tischler": ('["craft"="carpenter"]',),
    "zimmerer": ('["craft"="carpenter"]',),
    "gärtner": ('["craft"="gardener"]', '["shop"="garden_centre"]'),
    "bäckerei": ('["shop"="bakery"]',),
    "metzgerei": ('["shop"="butcher"]',),
    "friseur": ('["shop"="hairdresser"]',),
    "restaurant": ('["amenity"="restaurant"]',),
    "hotel": ('["tourism"="hotel"]',),
    "arzt": ('["amenity"="doctors"]',),
    "zahnarzt": ('["amenity"="dentist"]',),
    "steuerberater": ('["office"="tax_advisor"]',),
    "rechtsanwalt": ('["office"="lawyer"]',),
    "autowerkstatt": ('["shop"="car_repair"]',),
}


class OverpassProvider:
    """OpenStreetMap over the Overpass API.

    NOT COVERED BY TESTS. It makes real requests to a volunteer-run service.

    Free, no key, and the only platform here that publishes email addresses in
    the data itself (`contact:email`) — for the minority of businesses whose
    entry somebody bothered to fill in. Overpass asks for a descriptive
    User-Agent and gets one; hammering it is how the whole project's IP range
    gets blocked.
    """

    platform = Platform.OPENSTREETMAP
    ENDPOINT = "https://overpass-api.de/api/interpreter"

    def __init__(self, *, timeout_s: float = 60.0, endpoint: str | None = None) -> None:
        self._timeout_s = timeout_s
        self._endpoint = endpoint or self.ENDPOINT

    def build_query(self, area: SearchArea, query: str) -> str:
        """The Overpass QL for one area search.

        Pure string building, so this one *is* testable without a network — the
        part that talks to Overpass is `search`.
        """
        filters = OSM_TAG_HINTS.get(area.what.strip().lower())
        if filters is None:
            # No mapping for this trade: fall back to a case-insensitive name
            # search, which finds fewer businesses but never the wrong kind.
            escaped = re.sub(r'["\\]', "", area.what.strip())
            filters = (f'["name"~"{escaped}",i]',)

        place = re.sub(r'["\\]', "", area.where.strip())
        selectors = "\n  ".join(f"nwr{selector}(area.searchArea);" for selector in filters)

        return (
            f"[out:json][timeout:{int(self._timeout_s)}];\n"
            f'area["name"="{place}"]->.searchArea;\n'
            f"(\n  {selectors}\n);\n"
            f"out center tags {area.limit};"
        )

    def search(self, area: SearchArea, query: str) -> list[Listing]:  # pragma: no cover - network
        request = urllib.request.Request(
            self._endpoint,
            data=urllib.parse.urlencode({"data": self.build_query(area, query)}).encode("utf-8"),
            headers={"User-Agent": USER_AGENT},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=self._timeout_s + 10) as response:
            body = json.loads(response.read().decode("utf-8"))

        listings = [self._to_listing(element) for element in body.get("elements", [])]
        return [listing for listing in listings if listing.name]

    def _to_listing(self, element: dict[str, Any]) -> Listing:  # pragma: no cover - network
        tags = element.get("tags", {})
        center = element.get("center", {})
        element_type = element.get("type", "node")
        element_id = element.get("id", "")

        return Listing(
            platform=self.platform,
            platform_id=f"{element_type}/{element_id}",
            name=tags.get("name", ""),
            street=" ".join(
                part
                for part in (tags.get("addr:street", ""), tags.get("addr:housenumber", ""))
                if part
            ),
            postal_code=tags.get("addr:postcode", ""),
            city=tags.get("addr:city", ""),
            country=tags.get("addr:country", "DE"),
            latitude=element.get("lat", center.get("lat")),
            longitude=element.get("lon", center.get("lon")),
            phone_raw=tags.get("phone") or tags.get("contact:phone", ""),
            email_raw=tags.get("email") or tags.get("contact:email", ""),
            website=tags.get("website") or tags.get("contact:website", ""),
            categories=[
                f"{key}={value}"
                for key, value in tags.items()
                if key in {"craft", "shop", "office", "amenity"}
            ],
            source_url=f"https://www.openstreetmap.org/{element_type}/{element_id}",
            retrieved_at=datetime.now(UTC),
        )


# --- Company websites (live) -------------------------------------------


class HttpPageFetcher:
    """Fetches a business's imprint and contact pages.

    NOT COVERED BY TESTS. It makes real requests to third-party websites.

    Three things it will not do, each of which is a deliberate constraint rather
    than an oversight:

    * It does not fetch a page `robots.txt` disallows, and a site with no
      `robots.txt` counts as allowed, which is what the standard says.
    * It does not crawl. It reads the homepage, follows links whose path looks
      like an imprint or contact page, and stops — at most `max_pages` requests
      per business.
    * It waits `delay_s` between requests to one host. A lead run that takes
      four minutes instead of forty seconds is a fair trade for not being a
      nuisance to a small business's shared hosting.

    What it collects is what German law requires that business to publish
    openly. That is a lawful basis for *reading* it, not for anything you do
    next — see `agents/outreach/policy.py`, which is where that question lives.
    """

    def __init__(
        self,
        *,
        max_pages: int = 4,
        timeout_s: float = 15.0,
        delay_s: float = 1.0,
        respect_robots: bool = True,
    ) -> None:
        self.max_pages = max_pages
        self.timeout_s = timeout_s
        self.delay_s = delay_s
        self.respect_robots = respect_robots

    def fetch(self, website: str) -> list[WebPage]:  # pragma: no cover - network
        if not website:
            return []

        base = website if website.startswith(("http://", "https://")) else f"https://{website}"
        robots = self._robots_for(base)

        pages: list[WebPage] = []
        home = self._get(base, robots)
        if home is None:
            return []
        pages.append(home)

        for url in self._contact_links(base, home.text)[: self.max_pages - 1]:
            time.sleep(self.delay_s)
            page = self._get(url, robots)
            if page is not None:
                pages.append(page)

        return pages

    # -- internals -------------------------------------------------------

    def _robots_for(self, base: str):  # pragma: no cover - network
        if not self.respect_robots:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(urllib.parse.urljoin(base, "/robots.txt"))
        try:
            parser.read()
        except (urllib.error.URLError, OSError):
            # No reachable robots.txt means no stated restriction.
            return None
        return parser

    def _get(self, url: str, robots) -> WebPage | None:  # pragma: no cover - network
        if robots is not None and not robots.can_fetch(USER_AGENT, url):
            return None

        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read(2_000_000).decode(charset, errors="replace")
        except (urllib.error.URLError, OSError, ValueError):
            return None

        return WebPage(url=url, kind=page_kind(url), text=html_to_text(raw))

    def _contact_links(self, base: str, text: str) -> list[str]:  # pragma: no cover - network
        # Links were preserved by html_to_text as "→ href" markers, so the same
        # stripped text serves both extraction and navigation.
        found: dict[str, None] = {}
        for match in re.finditer(r"→\s*(\S+)", text):
            href = match.group(1)
            if any(hint in href.lower() for hint in CONTACT_PATH_HINTS):
                absolute = urllib.parse.urljoin(base, href)
                if domain_of(absolute) == domain_of(base):
                    found.setdefault(absolute, None)
        return list(found)


def page_kind(url: str) -> str:
    """Classify a page by its path. Extraction reads this."""
    lowered = url.lower()
    for hint, kind in _PAGE_KIND_HINTS:
        if hint in lowered:
            return kind
    return "home" if urllib.parse.urlparse(lowered).path.strip("/") == "" else "other"


_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_MAILTO_RE = re.compile(r'href=["\']mailto:([^"\'?]+)', re.IGNORECASE)
_TEL_RE = re.compile(r'href=["\']tel:([^"\']+)', re.IGNORECASE)
_HREF_RE = re.compile(r'<a\b[^>]*href=["\']([^"\'#]+)["\']', re.IGNORECASE)
_BREAK_RE = re.compile(r"</(p|div|li|tr|h[1-6])>|<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(markup: str) -> str:
    """Reduce HTML to the text an extractor can work on.

    `mailto:` and `tel:` targets are lifted out first and re-inserted as labelled
    lines. Half of all small-business sites put the address only in the link
    target, never in the visible text, and stripping tags first loses it.
    """
    body = _SCRIPT_RE.sub(" ", markup)

    harvested = [f"E-Mail: {html.unescape(address)}" for address in _MAILTO_RE.findall(body)]
    harvested += [f"Telefon: {html.unescape(number)}" for number in _TEL_RE.findall(body)]
    links = [f"→ {html.unescape(href)}" for href in _HREF_RE.findall(body)]

    text = _BREAK_RE.sub("\n", body)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)

    lines = [" ".join(line.split()) for line in text.splitlines()]
    kept = [line for line in lines if line]

    return "\n".join([*kept, *harvested, *links])
