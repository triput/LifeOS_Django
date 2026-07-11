# ==============================================================================
# File: lifeos_app/services/telemetry/weather.py
# Description: Pluggable terrestrial weather adapters (BL-TELE-001)
# Component: Services / Telemetry
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Terrestrial weather — Open-Meteo, NWS, and OpenWeatherMap adapters."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from lifeos_app.models import AppSettings, SystemEnums

logger = logging.getLogger(__name__)

CACHE_TTL_WEATHER = 1800
FETCH_TIMEOUT_SECONDS = 1.5
NWS_USER_AGENT = "LifeOS/2.0 (personal cockpit; telemetry@lifeos.local)"

_WMO_LABELS: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


@dataclass(frozen=True)
class WeatherSnapshot:
    """Normalized terrestrial weather for the Tier 4 HUD."""

    temperature: float | None
    temperature_unit: str
    humidity: int | None
    wind_speed: float | None
    wind_unit: str
    condition_label: str
    condition_code: int | None
    provider: str
    fetched_at: datetime
    error: str = ""

    @property
    def temperature_display(self) -> str:
        if self.temperature is None:
            return "N/A"
        value = round(self.temperature)
        return f"{value}°{self.temperature_unit}"

    @property
    def wind_display(self) -> str:
        if self.wind_speed is None:
            return ""
        return f"{round(self.wind_speed)} {self.wind_unit}"

    def to_cache(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fetched_at"] = self.fetched_at.isoformat()
        return payload

    @classmethod
    def from_cache(cls, payload: dict[str, Any]) -> WeatherSnapshot:
        fetched = payload.get("fetched_at")
        if isinstance(fetched, str):
            fetched_at = datetime.fromisoformat(fetched)
        else:
            fetched_at = timezone.now()
        return cls(
            temperature=payload.get("temperature"),
            temperature_unit=payload.get("temperature_unit", "F"),
            humidity=payload.get("humidity"),
            wind_speed=payload.get("wind_speed"),
            wind_unit=payload.get("wind_unit", "mph"),
            condition_label=payload.get("condition_label", "Unknown"),
            condition_code=payload.get("condition_code"),
            provider=payload.get("provider", "unknown"),
            fetched_at=fetched_at,
            error=payload.get("error", ""),
        )

    @classmethod
    def placeholder(cls, *, provider: str, message: str = "Unavailable") -> WeatherSnapshot:
        return cls(
            temperature=None,
            temperature_unit="F",
            humidity=None,
            wind_speed=None,
            wind_unit="mph",
            condition_label=message,
            condition_code=None,
            provider=provider,
            fetched_at=timezone.now(),
            error=message,
        )


def is_us_location(lat: float | None, lon: float | None) -> bool:
    """Rough bounding-box check for US territories (default provider selection)."""
    if lat is None or lon is None:
        return False
    if 24.0 <= lat <= 49.5 and -125.0 <= lon <= -66.0:
        return True
    if 51.0 <= lat <= 71.5 and -170.0 <= lon <= -129.0:
        return True
    if 18.0 <= lat <= 23.0 and -161.0 <= lon <= -154.0:
        return True
    if 17.5 <= lat <= 18.6 and -67.5 <= lon <= -65.0:
        return True
    return False


def resolve_weather_provider(settings: AppSettings) -> str:
    """Pick provider slug — owner override or auto US/NWS vs Open-Meteo."""
    configured = (settings.weather_provider or SystemEnums.WeatherProvider.AUTO).strip()
    if configured and configured != SystemEnums.WeatherProvider.AUTO:
        return configured
    if is_us_location(settings.latitude, settings.longitude):
        return SystemEnums.WeatherProvider.NWS
    return SystemEnums.WeatherProvider.OPEN_METEO


def _wmo_label(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _WMO_LABELS.get(code, "Mixed conditions")


def _http_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _celsius_to_fahrenheit(value: float) -> float:
    return (value * 9 / 5) + 32


def _kmh_to_mph(value: float) -> float:
    return value * 0.621371


def _fetch_open_meteo(lat: float, lon: float, *, use_imperial: bool) -> WeatherSnapshot:
    params = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "temperature_unit": "fahrenheit" if use_imperial else "celsius",
            "wind_speed_unit": "mph" if use_imperial else "kmh",
        }
    )
    data = _http_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    current = data.get("current", {})
    code = current.get("weather_code")
    return WeatherSnapshot(
        temperature=current.get("temperature_2m"),
        temperature_unit="F" if use_imperial else "C",
        humidity=current.get("relative_humidity_2m"),
        wind_speed=current.get("wind_speed_10m"),
        wind_unit="mph" if use_imperial else "km/h",
        condition_label=_wmo_label(code),
        condition_code=code,
        provider=SystemEnums.WeatherProvider.OPEN_METEO,
        fetched_at=timezone.now(),
    )


def _fetch_nws(lat: float, lon: float, *, use_imperial: bool) -> WeatherSnapshot:
    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}
    points = _http_json(f"https://api.weather.gov/points/{lat},{lon}", headers=headers)
    stations_url = points.get("properties", {}).get("observationStations")
    if not stations_url:
        raise ValueError("NWS points response missing observation stations")
    stations = _http_json(stations_url, headers=headers)
    features = stations.get("features") or []
    if not features:
        raise ValueError("NWS returned no observation stations")
    station_id = features[0].get("properties", {}).get("stationIdentifier")
    if not station_id:
        raise ValueError("NWS station identifier missing")
    obs = _http_json(
        f"https://api.weather.gov/stations/{station_id}/observations/latest",
        headers=headers,
    )
    props = obs.get("properties", {})
    temp_c = props.get("temperature", {}).get("value")
    humidity = props.get("relativeHumidity", {}).get("value")
    wind_mps = props.get("windSpeed", {}).get("value")
    temperature = None
    wind_speed = None
    if temp_c is not None:
        temperature = _celsius_to_fahrenheit(temp_c) if use_imperial else temp_c
    if wind_mps is not None:
        wind_kmh = wind_mps * 3.6
        wind_speed = _kmh_to_mph(wind_kmh) if use_imperial else wind_kmh
    label = (props.get("textDescription") or "Unknown").strip()
    return WeatherSnapshot(
        temperature=temperature,
        temperature_unit="F" if use_imperial else "C",
        humidity=int(round(humidity)) if humidity is not None else None,
        wind_speed=wind_speed,
        wind_unit="mph" if use_imperial else "km/h",
        condition_label=label,
        condition_code=None,
        provider=SystemEnums.WeatherProvider.NWS,
        fetched_at=timezone.now(),
    )


def _fetch_openweathermap(
    lat: float,
    lon: float,
    *,
    api_key: str,
    use_imperial: bool,
) -> WeatherSnapshot:
    if not api_key:
        return WeatherSnapshot.placeholder(
            provider=SystemEnums.WeatherProvider.OPENWEATHERMAP,
            message="API key required",
        )
    units = "imperial" if use_imperial else "metric"
    params = urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "appid": api_key, "units": units}
    )
    data = _http_json(f"https://api.openweathermap.org/data/2.5/weather?{params}")
    main = data.get("main", {})
    weather = (data.get("weather") or [{}])[0]
    wind = data.get("wind", {})
    return WeatherSnapshot(
        temperature=main.get("temp"),
        temperature_unit="F" if use_imperial else "C",
        humidity=main.get("humidity"),
        wind_speed=wind.get("speed"),
        wind_unit="mph" if use_imperial else "m/s",
        condition_label=(weather.get("description") or "Unknown").title(),
        condition_code=weather.get("id"),
        provider=SystemEnums.WeatherProvider.OPENWEATHERMAP,
        fetched_at=timezone.now(),
    )


def _fetch_provider(
    provider: str,
    *,
    lat: float,
    lon: float,
    use_imperial: bool,
    api_key: str,
) -> WeatherSnapshot:
    if provider == SystemEnums.WeatherProvider.NWS:
        return _fetch_nws(lat, lon, use_imperial=use_imperial)
    if provider == SystemEnums.WeatherProvider.OPENWEATHERMAP:
        return _fetch_openweathermap(lat, lon, api_key=api_key, use_imperial=use_imperial)
    return _fetch_open_meteo(lat, lon, use_imperial=use_imperial)


def _cache_key(provider: str, lat: float, lon: float, *, use_imperial: bool) -> str:
    units = "imperial" if use_imperial else "metric"
    return f"telemetry:weather:{provider}:{lat:.4f}:{lon:.4f}:{units}"


def invalidate_weather_cache_for_coords(lat: float | None, lon: float | None) -> None:
    """Drop cached weather snapshots for a lat/lon (all providers × unit systems)."""
    if lat is None or lon is None:
        return
    for provider in SystemEnums.WeatherProvider:
        for use_imperial in (True, False):
            cache.delete(_cache_key(provider.value, float(lat), float(lon), use_imperial=use_imperial))


def fetch_weather(
    settings: AppSettings | None = None,
    *,
    force_refresh: bool = False,
) -> WeatherSnapshot:
    """Return cached or freshly fetched terrestrial weather."""
    settings = settings or AppSettings.get_solo()
    lat = settings.latitude
    lon = settings.longitude
    if lat is None or lon is None:
        return WeatherSnapshot.placeholder(provider="none", message="Location unset")

    provider = resolve_weather_provider(settings)
    key = _cache_key(provider, lat, lon, use_imperial=settings.use_imperial)
    if not force_refresh:
        cached = cache.get(key)
        if cached:
            return WeatherSnapshot.from_cache(cached)

    try:
        snapshot = _fetch_provider(
            provider,
            lat=lat,
            lon=lon,
            use_imperial=settings.use_imperial,
            api_key=settings.openweather_api_key,
        )
        cache.set(key, snapshot.to_cache(), CACHE_TTL_WEATHER)
        return snapshot
    except Exception as exc:  # noqa: BLE001 — never 500 the Tier 4 HUD
        logger.warning("Weather fetch failed (%s): %s", provider, exc)
        return WeatherSnapshot.placeholder(provider=provider, message="Unavailable")
