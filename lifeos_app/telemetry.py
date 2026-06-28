# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/telemetry.py
# Description: Telemetry adapters for Open-Meteo weather and NOAA geomagnetic feeds
# Component: Core / Telemetry Services
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-26
# ==============================================================================
"""Telemetry services for environment indicators.

Interoperates with Open-Meteo for local weather, sunrise, and sunset times,
and NOAA SWPC for planetary geomagnetic Kp index data (FR-HUD-004).
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

class OpenMeteoAdapter:
    """
    Adapter for querying weather and celestial timings from Open-Meteo.
    Uses latitude, longitude, and timezone from environment or defaults.
    """
    def __init__(self):
        # Default to Seattle location if not specified
        self.latitude = os.environ.get("LATITUDE", "47.6062")
        self.longitude = os.environ.get("LONGITUDE", "-122.3321")
        self.timezone = os.environ.get("TIMEZONE", "UTC")
        self.url = "https://api.open-meteo.com/v1/forecast"

    def get_telemetry(self) -> dict:
        """
        Fetches current temperature and daily sunrise/sunset timings.
        """
        from .models import AppSettings
        settings = AppSettings.get_solo()
        
        lat = str(settings.latitude) if settings.latitude is not None else self.latitude
        lon = str(settings.longitude) if settings.longitude is not None else self.longitude
        tz = settings.timezone if settings.timezone else self.timezone
        if tz and '/' not in tz and tz.upper() != 'UTC' and tz.lower() != 'auto':
            tz = 'auto'
        
        payload = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m",
            "daily": "sunrise,sunset",
            "timezone": tz,
        }
        if settings.use_imperial:
            payload["temperature_unit"] = "fahrenheit"
            
        try:
            response = requests.get(self.url, params=payload, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            temp = data.get("current", {}).get("temperature_2m")
            temp_unit = data.get("current_units", {}).get("temperature_2m", "°C")
            
            sunrise_list = data.get("daily", {}).get("sunrise", [])
            sunset_list = data.get("daily", {}).get("sunset", [])
            
            # Format times to display only the time portion HH:MM
            sunrise = sunrise_list[0].split("T")[1] if sunrise_list else "N/A"
            sunset = sunset_list[0].split("T")[1] if sunset_list else "N/A"
            
            return {
                "temperature": f"{temp}{temp_unit}" if temp is not None else "N/A",
                "sunrise": sunrise,
                "sunset": sunset,
                "status": "online",
            }
        except Exception as e:
            logger.error("Failed to query Open-Meteo telemetry: %s", e)
            return {
                "temperature": "N/A",
                "sunrise": "N/A",
                "sunset": "N/A",
                "status": "offline",
            }


class NoaaKpAdapter:
    """
    Adapter for querying the planetary K-index from NOAA SWPC.
    """
    def __init__(self):
        self.url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

    def get_kp_index(self) -> dict:
        """
        Fetches the latest recorded planetary Kp index value.
        """
        try:
            response = requests.get(self.url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
                
            if isinstance(data, list) and len(data) > 0:
                latest = data[-1]
                kp = None
                time_tag = ""
                
                if isinstance(latest, dict):
                    kp = latest.get("Kp")
                    time_tag = latest.get("time_tag", "")
                elif isinstance(latest, list) and len(data) > 1:
                    # Array of arrays, data[0] is header
                    header = data[0]
                    if isinstance(header, list):
                        try:
                            kp_idx = header.index("Kp")
                            time_idx = header.index("time_tag")
                        except ValueError:
                            kp_idx = 1
                            time_idx = 0
                    else:
                        kp_idx = 1
                        time_idx = 0
                        
                    if len(latest) > max(kp_idx, time_idx):
                        kp = latest[kp_idx]
                        time_tag = latest[time_idx]
                    
                # Format time tag to HH:MM (NOAA time format e.g. "2023-11-20 03:00:00.000")
                time_str = ""
                if time_tag:
                    parts = time_tag.split(" ")
                    if len(parts) > 1:
                        time_str = parts[1][:5]
                    elif "T" in time_tag:
                        time_str = time_tag.split("T")[1][:5]
                
                # Formulate status warning based on Kp index scale
                # Kp >= 5 means geomagnetic storm active
                level = float(kp) if kp is not None else 0.0
                status_label = "Quiet"
                if level >= 5.0:
                    status_label = "Storm Active"
                elif level >= 4.0:
                    status_label = "Unsettled"
                
                return {
                    "kp_index": kp if kp is not None else "N/A",
                    "time": time_str,
                    "condition": status_label,
                    "status": "online",
                }
            return {
                "kp_index": "N/A",
                "time": "N/A",
                "condition": "Unknown",
                "status": "offline",
            }
        except Exception as e:
            logger.error("Failed to query NOAA K-index telemetry: %s", e)
            return {
                "kp_index": "N/A",
                "time": "N/A",
                "condition": "Unknown",
                "status": "offline",
            }
