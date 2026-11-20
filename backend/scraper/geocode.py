"""Reverse geocoding to turn area-scan tile centers into real place names
(district / city) that Google Maps actually geocodes.

Why this matters: the Google `pb` search endpoint ignores the textual
`near <lat>,<lng>` suffix, snapping instead to the session's default region
(the US, with a US cookie). Querying `restaurant in Garki` (or better
`restaurant in Brooklyn, New York, United States`) geocodes correctly. We therefore
label every tile with its district + the polygon's city/country so the
search always targets the right place.

The polygon's center (lat/lng) is what drives the *country* (market) of an
area scan: `geocode_locality` returns "City, Country" for the center, and the
job resolves gl/hl from that. This needs no user input and no free-text magic.
Location searches instead let the user pick the country from a dropdown.

Provider choice: BigDataCloud's keyless client endpoint is the PRIMARY reverse
geocoder. It returns district/city/country in one call, is permissive about
rate limits, and (unlike Nominatim/OpenStreetMap) does not hard-block many
residential/server IPs. Nominatim is kept only as a fallback when BDC is
unavailable. NOTE: these calls go out directly from the server's own IP — they
are intentionally NOT routed through the Google proxy pool.
"""
import asyncio
import time

from curl_cffi import AsyncSession
from backend.config import IMPERSONATE

BDC = "https://api.bigdatacloud.net/data/reverse-geocode-client"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"

# BigDataCloud is permissive; a short spacing is plenty. Nominatim (fallback)
# requires <= 1 req/s, so we honour that on the fallback path.
_GEO_SEM = asyncio.Semaphore(1)
_CACHE: dict = {}
_rate_limited = False
_blocked = False


def _user_agent():
    # Contactable UA satisfies OSM's policy (set a real contact if operating at scale).
    return "google-map-extractor/1.0 (mailto:owner@example.com)"


def was_rate_limited() -> bool:
    return _rate_limited


def was_blocked() -> bool:
    return _blocked


def reset_rate_limited():
    global _rate_limited, _blocked
    _rate_limited = False
    _blocked = False


def _pick(data):
    if not data:
        return None, None, None, None
    addr = data.get("address") or {}
    district = None
    for k in ("suburb", "neighbourhood", "city_district", "quarter"):
        if addr.get(k):
            district = addr[k]
            break
    city = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("municipality"))
    state = addr.get("state") or addr.get("region")
    country = addr.get("country")
    return district, city, state, country


def _bdc_pick(data):
    """Extract (district, city, state, country) from a BigDataCloud response.

    BDC returns a full administrative hierarchy in `localityInfo.administrative`
    ordered by specificity (higher `order` = finer place, e.g. district /
    neighbourhood). We take the most specific name as the district label.
    """
    if not data:
        return None, None, None, None
    admin = (data.get("localityInfo") or {}).get("administrative") or []
    sorted_admin = sorted(admin, key=lambda a: a.get("order", 0))
    district = (sorted_admin[-1].get("name") if sorted_admin
                else (data.get("locality") or data.get("city")))
    city = data.get("city") or data.get("locality")
    state = data.get("principalSubdivision")
    country = data.get("countryName")
    return district, city, state, country


async def _bdc(lat: float, lng: float):
    # Coarse cache key (~3.3 km) keeps the number of unique lookups small and
    # lets neighbouring tiles share one result.
    key = ("bdc", round(lat / 0.03) * 0.03, round(lng / 0.03) * 0.03)
    if key in _CACHE:
        return _CACHE[key]
    async with _GEO_SEM:
        try:
            async with AsyncSession(impersonate=IMPERSONATE, timeout=10) as s:
                url = f"{BDC}?latitude={lat}&longitude={lng}&localityLanguage=en"
                for attempt in range(2):
                    try:
                        r = await s.get(url)
                        if r.status_code == 200:
                            data = r.json()
                            _CACHE[key] = data
                            await asyncio.sleep(0.2)  # BDC free tier is permissive
                            return data
                        if r.status_code in (401, 403):
                            # Hard block (forbidden / unauthorized) for this IP:
                            # remember it so the UI can warn and we skip the rest.
                            global _blocked
                            _blocked = True
                            break
                        if r.status_code == 429:
                            global _rate_limited
                            _rate_limited = True
                            await asyncio.sleep(min(2.0 * (attempt + 1), 6))
                            continue
                    except Exception:
                        pass
                    await asyncio.sleep(min(2.0 * (attempt + 1), 6))
        except Exception:
            pass
        _CACHE[key] = None
        return None


async def _geo(lat: float, lng: float, zoom: int):
    # Nominatim fallback. Coarse cache key (~3.3 km) keeps unique lookups small.
    key = (round(lat / 0.03) * 0.03, round(lng / 0.03) * 0.03, zoom)
    if key in _CACHE:
        return _CACHE[key]
    async with _GEO_SEM:
        try:
            async with AsyncSession(impersonate=IMPERSONATE, timeout=15) as s:
                url = f"{NOMINATIM}?format=jsonv2&zoom={zoom}&lat={lat}&lon={lng}"
                for attempt in range(2):
                    try:
                        r = await s.get(url, headers={"User-Agent": _user_agent()})
                        if r.status_code == 200:
                            data = r.json()
                            _CACHE[key] = data
                            await asyncio.sleep(1.0)  # OSM policy: <= 1 req/s
                            return data
                        if r.status_code == 429:
                            global _rate_limited
                            _rate_limited = True
                            await asyncio.sleep(min(2.0 * (attempt + 1), 6))
                            continue
                        if r.status_code in (401, 403):
                            global _blocked
                            _blocked = True
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(min(2.0 * (attempt + 1), 6))
        except Exception:
            pass
        _CACHE[key] = None
        return None


async def reverse_geocode(lat: float, lng: float) -> str | None:
    """District/suburb name for a tile center, or None on failure.

    BigDataCloud is primary (keyless, returns district-level names, not IP-blocked
    for most hosts); Nominatim is a fallback when BDC returns nothing usable.
    """
    district, _, _, _ = _bdc_pick(await _bdc(lat, lng))
    if district:
        return district
    ndistrict, _, _, _ = _pick(await _geo(lat, lng, 18))
    return ndistrict


def _assemble_locality(district, city, state, country) -> str | None:
    if city and country:
        return f"{city}, {country}"
    if state and country:
        return f"{state}, {country}"
    if country:
        return country
    if city:
        return city
    if state:
        return state
    return None


async def geocode_locality(lat: float, lng: float) -> str | None:
    """'City, Country' (or 'State, Country') for the area-scan center, used to
    target every tile to the right region. BigDataCloud primary; Nominatim fallback.
    """
    loc = _assemble_locality(*_bdc_pick(await _bdc(lat, lng)))
    if loc:
        return loc
    return _assemble_locality(*_pick(await _geo(lat, lng, 14)))
