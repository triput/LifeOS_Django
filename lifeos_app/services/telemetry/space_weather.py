# ==============================================================================
# File: lifeos_app/services/telemetry/space_weather.py
# Description: NOAA SWPC space weather for Tier 4 HUD
# Component: Services / Telemetry
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Space weather — NOAA SWPC planetary K-index (fixed provider in v1)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_KEY = "telemetry:space_weather"
CACHE_TTL_SPACE = 7200
FETCH_TIMEOUT_SECONDS = 1.5
SWPC_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"


@dataclass(frozen=True)
class SpaceWeatherSnapshot:
    """Normalized space weather for the Tier 4 HUD."""

    kp_index: float | None
    label: str
    fetched_at: datetime
    error: str = ""

    @property
    def display(self) -> str:
        if self.kp_index is None:
            return "N/A"
        return f"Kp {self.kp_index:g} · {self.label}"

    def to_cache(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fetched_at"] = self.fetched_at.isoformat()
        return payload

    @classmethod
    def from_cache(cls, payload: dict[str, Any]) -> SpaceWeatherSnapshot:
        fetched = payload.get("fetched_at")
        if isinstance(fetched, str):
            fetched_at = datetime.fromisoformat(fetched)
        else:
            fetched_at = timezone.now()
        return cls(
            kp_index=payload.get("kp_index"),
            label=payload.get("label", "Unknown"),
            fetched_at=fetched_at,
            error=payload.get("error", ""),
        )

    @classmethod
    def placeholder(cls, message: str = "Unavailable") -> SpaceWeatherSnapshot:
        return cls(kp_index=None, label=message, fetched_at=timezone.now(), error=message)


def _kp_label(kp: float) -> str:
    if kp < 5:
        return "Calm"
    if kp < 6:
        return "Moderate"
    if kp < 8:
        return "Active"
    return "Storm"


def _extract_kp(row: Any) -> float | None:
    """Parse Kp from current SWPC dict rows or legacy list-of-columns rows."""
    if isinstance(row, dict):
        raw = row.get("Kp", row.get("kp"))
    elif isinstance(row, (list, tuple)) and len(row) > 1:
        # Legacy product shape: ["time_tag", "Kp", ...] with a header row.
        raw = row[1]
    else:
        return None
    if raw is None or raw == "" or raw == "Kp":
        return None
    return float(raw)


def _fetch_kp_index() -> SpaceWeatherSnapshot:
    req = urllib.request.Request(SWPC_KP_URL, method="GET")
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("SWPC Kp feed empty")
    # Prefer the newest parseable observation (feed is chronological).
    kp = None
    for row in reversed(rows):
        kp = _extract_kp(row)
        if kp is not None:
            break
    if kp is None:
        raise ValueError("SWPC Kp feed missing Kp values")
    return SpaceWeatherSnapshot(
        kp_index=kp,
        label=_kp_label(kp),
        fetched_at=timezone.now(),
    )


def fetch_space_weather(*, force_refresh: bool = False) -> SpaceWeatherSnapshot:
    """Return cached or freshly fetched NOAA SWPC K-index."""
    if not force_refresh:
        cached = cache.get(CACHE_KEY)
        if cached:
            return SpaceWeatherSnapshot.from_cache(cached)

    try:
        snapshot = _fetch_kp_index()
        cache.set(CACHE_KEY, snapshot.to_cache(), CACHE_TTL_SPACE)
        return snapshot
    except Exception as exc:  # noqa: BLE001 — never 500 the Tier 4 HUD
        logger.warning("Space weather fetch failed: %s", exc)
        return SpaceWeatherSnapshot.placeholder()
