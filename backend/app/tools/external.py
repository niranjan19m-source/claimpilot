"""External data sources: historical weather (Open-Meteo), geocoding (offline
gazetteer, then OpenStreetMap Nominatim), and the vehicle registry (mocked VAHAN)."""
from __future__ import annotations

import json
import threading
from typing import Any

import httpx

from .. import db
from ..config import ALLOW_NETWORK, HTTP_USER_AGENT, WEATHER_CACHE
from .base import ToolResult, parse_date, signal

_lock = threading.Lock()

# Weather codes per WMO: 61-67 rain, 80-82 showers, 95-99 thunderstorm.
WEATHER_PERILS = {"flood", "storm", "hailstorm", "cyclone", "natural_calamity"}

GAZETTEER: dict[str, tuple[float, float]] = {
    "pune": (18.5204, 73.8567), "koregaon park": (18.5362, 73.8940), "hinjewadi": (18.5913, 73.7389),
    "baner": (18.5590, 73.7868), "kothrud": (18.5074, 73.8077), "mumbai": (19.0760, 72.8777),
    "andheri": (19.1136, 72.8697), "thane": (19.2183, 72.9781), "navi mumbai": (19.0330, 73.0297),
    "chennai": (13.0827, 80.2707), "velachery": (12.9815, 80.2180), "tambaram": (12.9249, 80.1000),
    "bengaluru": (12.9716, 77.5946), "bangalore": (12.9716, 77.5946), "whitefield": (12.9698, 77.7500),
    "koramangala": (12.9352, 77.6245), "hyderabad": (17.3850, 78.4867), "gachibowli": (17.4401, 78.3489),
    "delhi": (28.6139, 77.2090), "new delhi": (28.6139, 77.2090), "gurugram": (28.4595, 77.0266),
    "noida": (28.5355, 77.3910), "kolkata": (22.5726, 88.3639), "ahmedabad": (23.0225, 72.5714),
    "jaipur": (26.9124, 75.7873), "lucknow": (26.8467, 80.9462), "nashik": (19.9975, 73.7898),
    "nagpur": (21.1458, 79.0882), "kochi": (9.9312, 76.2673), "coimbatore": (11.0168, 76.9558),
}


# ------------------------------------------------------------------ geocoding
def geocode(location: str, city: str | None = None) -> ToolResult:
    q = f"{location or ''} {city or ''}".lower()
    for name in sorted(GAZETTEER, key=len, reverse=True):
        if name in q:
            lat, lon = GAZETTEER[name]
            return ToolResult(True, f"Resolved '{location}' to {name.title()} ({lat:.4f}, {lon:.4f}).",
                              {"lat": lat, "lon": lon, "matched": name.title(), "source": "gazetteer"})
    if ALLOW_NETWORK:
        try:
            r = httpx.get("https://nominatim.openstreetmap.org/search",
                          params={"q": f"{location}, {city or ''}, India", "format": "json", "limit": 1},
                          headers={"User-Agent": HTTP_USER_AGENT}, timeout=6)
            hits = r.json()
            if hits:
                lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
                return ToolResult(True, f"Resolved via OpenStreetMap to {hits[0]['display_name'][:80]}.",
                                  {"lat": lat, "lon": lon, "matched": hits[0]["display_name"], "source": "nominatim"})
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    return ToolResult(False, f"Could not geocode '{location}'.", {},
                      [signal("LOCATION_UNVERIFIED", "Loss location could not be verified", 5,
                              f"'{location}' did not resolve to a known place.")])


# ------------------------------------------------------------------ weather
def _cache() -> dict[str, Any]:
    if WEATHER_CACHE.exists():
        try:
            return json.loads(WEATHER_CACHE.read_text())
        except ValueError:
            return {}
    return {}


def _fetch_weather(lat: float, lon: float, start: str, end: str) -> dict | None:
    key = f"{lat:.2f},{lon:.2f},{start},{end}"
    cache = _cache()
    if key in cache:
        return {**cache[key], "_source": "cache"}
    if not ALLOW_NETWORK:
        return None
    try:
        r = httpx.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": round(lat, 2), "longitude": round(lon, 2), "start_date": start, "end_date": end,
            "daily": "precipitation_sum,rain_sum,wind_speed_10m_max,wind_gusts_10m_max,weather_code",
            "timezone": "Asia/Kolkata"}, timeout=8)
        r.raise_for_status()
        daily = r.json().get("daily")
        if not daily:
            return None
        with _lock:
            cache = _cache()
            cache[key] = daily
            WEATHER_CACHE.write_text(json.dumps(cache))
        return {**daily, "_source": "open-meteo"}
    except (httpx.HTTPError, ValueError):
        return None


def weather_check(claim: dict) -> ToolResult:
    from datetime import timedelta
    inc = parse_date(claim.get("incident_date"))
    lat, lon = claim.get("lat"), claim.get("lon")
    if not inc or lat is None:
        return ToolResult(False, "Weather check needs a loss date and a geocoded location.")
    start, end = str(inc - timedelta(days=2)), str(inc + timedelta(days=1))
    daily = _fetch_weather(float(lat), float(lon), start, end)
    if not daily:
        return ToolResult(False, "Historical weather service unavailable; peril not independently verified.",
                          {"verified": False})
    days = [{"date": d, "precip_mm": daily["precipitation_sum"][i],
             "wind_kmh": (daily.get("wind_speed_10m_max") or [None] * 10)[i],
             "gust_kmh": (daily.get("wind_gusts_10m_max") or [None] * 10)[i],
             "code": (daily.get("weather_code") or [None] * 10)[i]} for i, d in enumerate(daily["time"])]
    window = [d for d in days if d["date"] <= str(inc)]
    rain_72h = round(sum((d["precip_mm"] or 0) for d in window[-3:]), 1)
    loss_day = next((d for d in days if d["date"] == str(inc)), days[-1])
    peril = (claim.get("claim_type") or "").lower()
    max_gust = max((d["gust_kmh"] or 0) for d in window) if window else 0
    signals = []
    consistent = True
    if peril in {"flood", "natural_calamity"}:
        consistent = rain_72h >= 25
        if not consistent:
            signals.append(signal("WEATHER_MISMATCH", "No flooding-level rainfall at loss location", 30,
                                  f"Flood claimed on {inc}, but recorded rainfall over the 72h before the loss was "
                                  f"{rain_72h} mm (threshold 25 mm) at {lat:.2f},{lon:.2f}."))
    elif peril in {"storm", "cyclone"}:
        consistent = max_gust >= 50 or rain_72h >= 40
        if not consistent:
            signals.append(signal("WEATHER_MISMATCH", "No storm conditions recorded", 26,
                                  f"Storm claimed, but max gust was {max_gust} km/h and rain {rain_72h} mm."))
    elif peril == "hailstorm":
        consistent = any((d["code"] or 0) >= 95 for d in window)
        if not consistent:
            signals.append(signal("WEATHER_MISMATCH", "No thunderstorm/hail recorded", 26,
                                  f"Hail claimed, but no thunderstorm weather code recorded {start}–{inc}."))
    summary = (f"{'Consistent' if consistent else 'INCONSISTENT'}: {rain_72h} mm rain in 72h to {inc}, "
               f"{loss_day['precip_mm']} mm on the day, max gust {max_gust} km/h (source: {daily.get('_source')}).")
    return ToolResult(True, summary, {"verified": True, "consistent": consistent, "rain_72h_mm": rain_72h,
                                      "days": days, "source": daily.get("_source"), "peril": peril}, signals)


# ------------------------------------------------------------------ vehicle registry
def vehicle_registry(reg_no: str, policy_vehicle: dict | None = None) -> ToolResult:
    reg = (reg_no or "").replace(" ", "").upper()
    row = db.one("SELECT details FROM policies WHERE REPLACE(json_extract(details, '$.vehicle.reg'), ' ', '') = ?", (reg,))
    if not row:
        return ToolResult(False, f"Registration {reg} not found in registry.", {"reg": reg},
                          [signal("REG_NOT_FOUND", "Vehicle not found in registry", 20, f"{reg} has no registry record.")])
    v = db.loads(row["details"], {}).get("vehicle", {})
    rec = {"reg": v.get("reg"), "make_model": v.get("make_model"), "year": v.get("year"), "fuel": v.get("fuel"),
           "chassis_no": v.get("chassis_no"), "engine_no": v.get("engine_no"),
           "hypothecation": v.get("hypothecation"), "commercial_permit": v.get("commercial_permit", False),
           "registry_status": "ACTIVE"}
    signals = []
    if rec["commercial_permit"]:
        signals.append(signal("COMMERCIAL_PERMIT", "Vehicle holds a commercial (taxi) permit", 0,
                              "Registry shows a contract-carriage permit on a private-car policy.", "coverage"))
    return ToolResult(True, f"{rec['reg']}: {rec['make_model']} ({rec['year']}, {rec['fuel']}), registry ACTIVE"
                      + ("; COMMERCIAL PERMIT" if rec["commercial_permit"] else "") + ".", rec, signals)
