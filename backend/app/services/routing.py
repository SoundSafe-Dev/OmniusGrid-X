"""Routing / distance provider seam (FS-26).

Replaces the flat 500-mile placeholder in transportation_management with a real
great-circle (haversine) estimate that sums through waypoints and accepts both
coordinate key styles used across the app ({lat,lng} and {latitude,longitude}).

A provider seam lets a self-hosted OSRM (or a keyed Google/HERE) return true
road distances when configured; the haversine provider is the always-available
default. Selection is via ROUTING_PROVIDER; unknown/unconfigured providers fall
back to haversine rather than failing a shipment estimate.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import structlog

from app.core.config import settings

logger = structlog.get_logger()

# Great-circle distance underestimates road distance; this factor approximates
# real road routing (industry-typical ~1.2–1.3x for highway freight).
ROAD_FACTOR = 1.2
_EARTH_RADIUS_MI = 3959.0


def _coords(point: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    """Extract (lat, lng) from either {lat,lng} or {latitude,longitude}."""
    if not point:
        return None
    lat = point.get("latitude", point.get("lat"))
    lng = point.get("longitude", point.get("lng"))
    if lat in (None, 0) and lng in (None, 0):
        return None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def haversine_miles(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return _EARTH_RADIUS_MI * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _leg_points(origin, destination, waypoints) -> List[Tuple[float, float]]:
    seq = [origin] + list(waypoints or []) + [destination]
    return [c for c in (_coords(p) for p in seq) if c is not None]


def _haversine_route(origin, destination, waypoints) -> Optional[float]:
    pts = _leg_points(origin, destination, waypoints)
    if len(pts) < 2:
        return None
    miles = sum(haversine_miles(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return round(miles * ROAD_FACTOR, 1)


def _osrm_route(origin, destination, waypoints) -> Optional[float]:
    """Real road distance from a self-hosted OSRM server (ROUTING_OSRM_URL)."""
    base = settings.ROUTING_OSRM_URL
    pts = _leg_points(origin, destination, waypoints)
    if not base or len(pts) < 2:
        return None
    # OSRM expects lng,lat pairs.
    coord_str = ";".join(f"{lng},{lat}" for lat, lng in pts)
    url = f"{base.rstrip('/')}/route/v1/driving/{coord_str}?overview=false"
    try:
        import httpx
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        meters = data["routes"][0]["distance"]
        return round(meters / 1609.34, 1)
    except Exception as e:  # noqa: BLE001
        logger.warning("osrm_route_failed", error=str(e))
        return None


def estimate_distance_miles(
    origin: Dict[str, Any],
    destination: Dict[str, Any],
    waypoints: Optional[List[Dict[str, Any]]] = None,
) -> float:
    """Best available distance estimate in miles.

    OSRM when configured and reachable, else haversine, else a coarse default
    (only when NO usable coordinates exist at all).
    """
    if settings.ROUTING_PROVIDER == "osrm":
        osrm = _osrm_route(origin, destination, waypoints)
        if osrm is not None:
            return osrm
        # fall through to haversine rather than failing the estimate

    hav = _haversine_route(origin, destination, waypoints)
    if hav is not None:
        return hav

    logger.warning("routing_no_coordinates", note="using coarse default distance")
    return 500.0
