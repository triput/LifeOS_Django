# ==============================================================================
# File: lifeos_app/services/telemetry/geocode.py
# Description: Forward geocode place labels → lat/lon (BL-TELE-005)
# Component: Services / Telemetry
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Resolve typed city/state(/country) via Open-Meteo Geocoding (no API key)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FETCH_TIMEOUT_SECONDS = 2.5
USER_AGENT = "LifeOS/2.0 (personal cockpit; geocode@lifeos.local)"

# Common US state / territory abbreviations → Open-Meteo admin1 names.
US_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "PR": "Puerto Rico",
}

# Loose country token → ISO 3166-1 alpha-2 for Open-Meteo countryCode.
COUNTRY_CODES: dict[str, str] = {
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "UK": "GB",
    "GB": "GB",
    "GREAT BRITAIN": "GB",
    "UNITED KINGDOM": "GB",
    "ENGLAND": "GB",
    "SCOTLAND": "GB",
    "WALES": "GB",
    "CA": "CA",
    "CANADA": "CA",
    "MX": "MX",
    "MEXICO": "MX",
    "AU": "AU",
    "AUSTRALIA": "AU",
    "DE": "DE",
    "GERMANY": "DE",
    "FR": "FR",
    "FRANCE": "FR",
    "JP": "JP",
    "JAPAN": "JP",
    "IN": "IN",
    "INDIA": "IN",
    "IE": "IE",
    "IRELAND": "IE",
    "NZ": "NZ",
    "NEW ZEALAND": "NZ",
}


@dataclass(frozen=True)
class PlaceQuery:
    """Normalized search intent from a free-text location label."""

    name: str
    admin1: str = ""
    country_code: str = "US"


@dataclass(frozen=True)
class GeocodeHit:
    """One geocoder candidate."""

    latitude: float
    longitude: float
    label: str
    country_code: str = ""
    admin1: str = ""
    name: str = ""


@dataclass(frozen=True)
class GeocodeResult:
    """Outcome of a forward geocode attempt."""

    ok: bool
    message: str = ""
    hit: GeocodeHit | None = None
    candidates: tuple[GeocodeHit, ...] = ()


def _expand_us_state(token: str) -> str:
    raw = (token or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in US_STATE_NAMES:
        return US_STATE_NAMES[upper]
    # Already a full name — title-case lightly
    return raw


def _country_code(token: str) -> str | None:
    key = (token or "").strip().upper()
    if not key:
        return None
    if len(key) == 2 and key.isalpha():
        return COUNTRY_CODES.get(key, key)
    return COUNTRY_CODES.get(key)


def parse_place_label(raw: str) -> PlaceQuery | None:
    """
    Parse ``city, state`` (US default) or ``city, region, country``.

    Examples: ``Phoenix, AZ`` · ``London, England, UK`` · ``Toronto, ON, Canada``
    """
    text = (raw or "").strip()
    if not text:
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return PlaceQuery(name=parts[0], country_code="US")
    if len(parts) == 2:
        city, second = parts
        # If second token is a known non-US country, treat as city, country
        cc = _country_code(second)
        if cc and cc != "US" and second.upper() not in US_STATE_NAMES and len(second) > 2:
            return PlaceQuery(name=city, country_code=cc)
        return PlaceQuery(name=city, admin1=_expand_us_state(second), country_code="US")
    # 3+ : city, region, …, country
    city = parts[0]
    country_token = parts[-1]
    region = parts[1]
    cc = _country_code(country_token) or "US"
    admin1 = _expand_us_state(region) if cc == "US" else region
    return PlaceQuery(name=city, admin1=admin1, country_code=cc)


def _format_label(row: dict) -> str:
    name = (row.get("name") or "").strip()
    admin1 = (row.get("admin1") or "").strip()
    country = (row.get("country") or "").strip()
    cc = (row.get("country_code") or "").strip().upper()
    parts: list[str] = []
    if name:
        parts.append(name)
    if admin1 and admin1 != name:
        parts.append(admin1)
    if cc and cc != "US" and country:
        parts.append(country)
    return ", ".join(parts)[:255] or name


def _row_to_hit(row: dict) -> GeocodeHit | None:
    try:
        lat = float(row["latitude"])
        lon = float(row["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return GeocodeHit(
        latitude=round(lat, 4),
        longitude=round(lon, 4),
        label=_format_label(row),
        country_code=(row.get("country_code") or "").upper(),
        admin1=(row.get("admin1") or "").strip(),
        name=(row.get("name") or "").strip(),
    )


def _admin1_matches(hit_admin: str, wanted: str) -> bool:
    if not wanted:
        return True
    a = hit_admin.casefold()
    b = wanted.casefold()
    return a == b or a.startswith(b) or b.startswith(a)


def _rank_hits(hits: list[GeocodeHit], query: PlaceQuery) -> list[GeocodeHit]:
    """Prefer admin1 match, then exact city name."""
    scored: list[tuple[int, GeocodeHit]] = []
    for hit in hits:
        score = 0
        if query.admin1 and _admin1_matches(hit.admin1, query.admin1):
            score += 10
        if hit.name.casefold() == query.name.casefold():
            score += 5
        if query.country_code and hit.country_code == query.country_code:
            score += 2
        scored.append((score, hit))
    scored.sort(key=lambda pair: (-pair[0], pair[1].label))
    return [h for _, h in scored]


def _http_search(*, name: str, country_code: str, count: int = 8) -> list[dict]:
    params = {
        "name": name,
        "count": str(count),
        "language": "en",
        "format": "json",
    }
    if country_code:
        params["countryCode"] = country_code
    url = f"{GEOCODE_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rows = payload.get("results") or []
    return rows if isinstance(rows, list) else []


def geocode_place(raw: str) -> GeocodeResult:
    """Forward-geocode a location label; returns best hit + short candidate list."""
    query = parse_place_label(raw)
    if query is None:
        return GeocodeResult(ok=False, message="Enter a place like Phoenix, AZ or London, England, UK.")
    try:
        rows = _http_search(name=query.name, country_code=query.country_code)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Geocode failed for %r: %s", raw, exc)
        return GeocodeResult(ok=False, message="Geocoder unavailable — enter lat/lon manually.")

    hits = [h for row in rows if (h := _row_to_hit(row))]
    if not hits:
        return GeocodeResult(
            ok=False,
            message=f"No matches for “{raw.strip()}”. Try city, state or add a country.",
        )
    ranked = _rank_hits(hits, query)
    # If admin1 was specified, prefer filtered set when any match
    if query.admin1:
        filtered = [h for h in ranked if _admin1_matches(h.admin1, query.admin1)]
        if filtered:
            ranked = filtered + [h for h in ranked if h not in filtered]
    best = ranked[0]
    others = tuple(ranked[1:4])
    msg = f"Resolved to {best.label}."
    if others:
        msg += f" Other matches: {', '.join(c.label for c in others)}."
    return GeocodeResult(ok=True, message=msg, hit=best, candidates=others)
