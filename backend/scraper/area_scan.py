"""Area scan: generate a grid of coordinate centers covering a radius.

The Google search endpoint is query-driven (no explicit center param in our
reused pb), so we bias each tiled search with a 'near <lat>,<lng>' suffix.
This is best-effort geo-coverage to overcome the per-query result cap.
"""
import math


def grid_centers(lat: float, lng: float, radius_km: float, max_points: int = 25):
    """Return list of (lat, lng) covering a square ~2*radius around center."""
    # spacing ~ radius/2, but keep total points bounded
    step = max(radius_km / 2.0, 1.0)
    n = int((2 * radius_km) / step) + 1
    n = max(1, min(n, int(math.sqrt(max_points))))
    step = (2 * radius_km) / n if n > 1 else 0
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    pts = []
    for i in range(n):
        for j in range(n):
            plat = lat - dlat + (2 * dlat) * (i / max(n - 1, 1))
            plng = lng - dlng + (2 * dlng) * (j / max(n - 1, 1))
            pts.append((round(plat, 5), round(plng, 5)))
    return pts


def build_area_queries(query: str, centers, labels=None, locality=None):
    """Build one search query per tile center.

    Each query becomes `query in <district>, <locality>` (e.g.
    "restaurant in Brooklyn, New York, United States") — a form Google actually geocodes.
    `locality` (the polygon's city/country) guarantees every tile targets the
    right region even when a per-tile district lookup fails, so we never fall
    back to the ignored `near <lat>,<lng>` form. Identical queries (tiles that
    share the same district) are collapsed into one search.
    """
    if labels is not None or locality:
        out, seen = [], set()
        for (la, ln), lab in zip(centers, labels or [None] * len(centers)):
            if lab and locality:
                loc = f"{lab}, {locality}"
            elif lab:
                loc = lab
            elif locality:
                # No district for this tile: anchor with the tile's own
                # coordinates so the query stays distinct from its neighbours
                # (otherwise every tile collapses to one identical query).
                loc = f"{locality} near {la},{ln}"
            else:
                loc = f"{la},{ln}"   # last-resort only
            q = f"{query} in {loc}"
            if q not in seen:
                seen.add(q)
                out.append(q)
        return out
    return [f"{query} near {la},{ln}" for la, ln in centers]


def point_in_polygon(lat: float, lng: float, polygon) -> bool:
    """Ray-casting point-in-polygon. `polygon` is a list of [lat, lng]."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][1], polygon[i][0]   # x = lng, y = lat
        xj, yj = polygon[j][1], polygon[j][0]
        intersect = ((yi > lat) != (yj > lat)) and \
            (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def grid_in_polygon(polygon, max_points: int = 400, spacing_km: float = 1.2):
    """Generate an even grid of search centers inside the drawn polygon.

    Tile *spacing* is driven by real-world distance (`spacing_km`), so a tiny
    box yields only a handful of tiles instead of the full cap (avoiding
    hundreds of duplicate searches of the same spot). `max_points` stays a hard
    ceiling so a huge area never explodes into thousands of requests. Returns
    list of (lat, lng) ready for `build_area_queries`.
    """
    if not polygon or len(polygon) < 3:
        return []
    lats = [p[0] for p in polygon]
    lngs = [p[1] for p in polygon]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)
    span_lat = max_lat - min_lat
    span_lng = max_lng - min_lng
    if span_lat == 0 and span_lng == 0:
        return [(round(polygon[0][0], 5), round(polygon[0][1], 5))]

    # Desired grid counts per axis from a real-world spacing (deg -> km).
    mid_lat = (min_lat + max_lat) / 2
    lat_span_km = span_lat * 111.32
    lng_span_km = span_lng * 111.32 * math.cos(math.radians(mid_lat))
    n_lat = max(1, int(round(lat_span_km / spacing_km)) + 1)
    n_lng = max(1, int(round(lng_span_km / spacing_km)) + 1)

    # Cap total tiles at max_points by scaling both axes down proportionally.
    desired = n_lat * n_lng
    if desired > max_points:
        scale = math.sqrt(desired / max_points)
        n_lat = max(1, int(n_lat / scale))
        n_lng = max(1, int(n_lng / scale))

    def _in(lat, lng):
        if point_in_polygon(lat, lng, polygon):
            return True
        # Tolerate points sitting exactly on an edge (ray-casting is ambiguous
        # there) so boundary tiles aren't dropped.
        for dlat, dlng in ((1e-4, 0), (-1e-4, 0), (0, 1e-4), (0, -1e-4)):
            if point_in_polygon(lat + dlat, lng + dlng, polygon):
                return True
        return False

    step_lat = span_lat / (n_lat - 1) if n_lat > 1 else 0
    step_lng = span_lng / (n_lng - 1) if n_lng > 1 else 0
    pts = []
    for i in range(n_lat):
        for j in range(n_lng):
            lat = min_lat + i * step_lat
            lng = min_lng + j * step_lng
            if _in(lat, lng):
                pts.append((round(lat, 5), round(lng, 5)))
    return pts
