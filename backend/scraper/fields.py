"""Canonical business record + extraction from the place-details JSON (j[6]).

Verified paths come from research/00_RESEARCH_LOG.md. Phone / email are
best-effort (pattern scans) since they were not present in the sampled
business.
"""
import re
import json
from dataclasses import dataclass, field, asdict


@dataclass
class Business:
    cid: str = ""
    name: str = ""
    category: str = ""
    street: str = ""
    city_state_zip: str = ""
    full_address: str = ""
    rating: float | None = None
    reviews_count: int | None = None
    website: str = ""
    phone: str = ""
    email: str = ""
    latitude: float | None = None
    longitude: float | None = None
    place_id: str = ""
    gid: str = ""
    timezone: str = ""
    thumbnail: str = ""
    is_ad: bool = False
    # --- extended details (from /maps/preview/place) ---
    price_level: int | None = None
    price_desc: str = ""
    hours: str = ""            # JSON: {day: [range, ...]}
    popular_times: str = ""    # JSON: {day: [{hour,pop,label,busy}, ...]}
    menu_url: str = ""
    closed_status: str = ""
    amenities: str = ""
    service_options: str = ""
    highlights: str = ""
    popular_for: str = ""
    # --- enrichment (website scrape + reviews endpoint) ---
    emails: str = "[]"         # JSON list
    socials: str = "[]"        # JSON list of URLs
    reviews: str = "[]"        # JSON list of {author,rating,text,time,photo}
    web_tech: str = "{}"       # JSON: {ssl, cms, has_contact_form, ...} website analysis
    site_text: str = ""        # Clean stripped visible text from website for AI analysis
    # --- lead scoring (computed by backend.scraper.leadscore) ---
    lead_score: int = 0
    lead_grade: str = ""
    lead_reasons: str = "[]"    # JSON list of plain-language reasons
    lead_tags: str = "[]"       # JSON list of machine tags
    raw_json: str = ""

    def to_row(self) -> dict:
        d = asdict(self)
        d["is_ad"] = 1 if self.is_ad else 0
        return d


# Require real phone formatting: a '+' prefix OR at least one separator
# (space / dash / dot / parens) so we don't match bare numeric IDs.
_PHONE_RE = re.compile(
    r"(?:\+1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}"
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _strip_quotes(s):
    """Google wraps many string values in a single pair of quotes inside the
    JSON (e.g. "'80-57 Lefferts Boulevard'"). Strip one layer if present."""
    if isinstance(s, str) and len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1]
    return s


def _walk(o, pred):
    """Yield first value in nested structure matching pred."""
    if pred(o):
        return o
    if isinstance(o, dict):
        for v in o.values():
            r = _walk(v, pred)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _walk(v, pred)
            if r is not None:
                return r
    return None


def _first_image(rec) -> str:
    def is_img(v):
        return isinstance(v, str) and v.startswith("http") and "googleusercontent" in v
    r = _walk(rec, is_img)
    return r or ""


def _extract_place_id(rec) -> str:
    blob = json.dumps(rec)
    m = re.search(r"placeid=([A-Za-z0-9_\-]+)", blob)
    if m:
        return m.group(1)
    return ""


def _extract_hours(rec):
    try:
        days = rec[203][0]
        if not isinstance(days, list):
            return None
        out = {}
        for d in days:
            if not isinstance(d, list) or len(d) < 4:
                continue
            name = d[0]
            ranges = d[3]
            if not isinstance(ranges, list) or not name:
                continue
            parts = []
            for r in ranges:
                if isinstance(r, list) and r and isinstance(r[0], str):
                    parts.append(r[0])
                elif isinstance(r, str):
                    parts.append(r)
            if parts:
                out[name] = parts
        return out or None
    except Exception:
        return None


def _extract_popular_times(rec):
    try:
        blocks = rec[84][0]
        if not isinstance(blocks, list):
            return None
        out = {}
        for b in blocks:
            if not isinstance(b, list) or len(b) < 2:
                continue
            day = b[0]
            buckets = b[1]
            if not isinstance(buckets, list):
                continue
            series = []
            for bucket in buckets:
                if not isinstance(bucket, list):
                    continue
                series.append({
                    "hour": bucket[0] if len(bucket) > 0 else None,
                    "pop": bucket[1] if len(bucket) > 1 else None,
                    "label": bucket[4] if len(bucket) > 4 else None,
                    "busy": bucket[2] if len(bucket) > 2 else None,
                })
            if series:
                out[day] = series
        return out or None
    except Exception:
        return None


_PRICE_MAP = {"Inexpensive": 1, "Moderate": 2, "Expensive": 3, "Very expensive": 4}


def _extract_price(rec):
    try:
        node = None
        try:
            if (len(rec) > 100 and isinstance(rec[100], list) and len(rec[100]) > 5
                    and isinstance(rec[100][5], list) and len(rec[100][5]) > 11):
                node = rec[100][5][11]
        except Exception:
            node = None
        if not isinstance(node, list) or len(node) < 3 or not isinstance(node[2], list):
            return None, None
        desc = None
        for e in node[2]:
            if isinstance(e, list) and len(e) >= 3 and isinstance(e[1], str) and e[1] == "Price level":
                sub = e[2]
                if isinstance(sub, list) and len(sub) > 3 and isinstance(sub[3], list) and len(sub[3]) > 2:
                    desc = sub[3][2]
        if not desc:
            return None, None
        return _PRICE_MAP.get(desc), desc
    except Exception:
        return None, None


def _extract_menu(rec):
    try:
        m = rec[7][0]
        if isinstance(m, str) and m.startswith("http"):
            return m
    except Exception:
        return None
    return None


def _extract_closed(rec):
    try:
        blob = json.dumps(rec)
        m = re.search(r"(Permanently closed|Temporarily closed)", blob, re.I)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _items_of(block):
    """Extract human-readable labels from a Google attributes block.

    Each item is typically [taxonomy_uri, human_label, ...] (e.g.
    ['/geo/type/establishment_poi/has_delivery', 'Offers delivery', ...]).
    We must skip the /geo/ taxonomy URIs and keep the readable label.
    """
    out = []
    if not isinstance(block, list) or len(block) < 3:
        return out
    its = block[2]
    if not isinstance(its, list):
        return out
    for it in its:
        if isinstance(it, str):
            if not it.startswith("/geo/"):
                out.append(it)
        elif isinstance(it, list):
            label = None
            for x in it:
                if isinstance(x, str) and not x.startswith("/geo/"):
                    label = x
                    break
            if label:
                out.append(label)
    return out


def _extract_attributes(rec):
    try:
        node = (rec[100][1] if (len(rec) > 100 and isinstance(rec[100], list)
                and len(rec[100]) > 1 and isinstance(rec[100][1], list)) else None)
        if not node:
            return None, None, None, None
        svc = "; ".join(_items_of(node[0])) if len(node) > 0 and isinstance(node[0], list) else ""
        hl = "; ".join(_items_of(node[1])) if len(node) > 1 and isinstance(node[1], list) else ""
        pf = "; ".join(_items_of(node[2])) if len(node) > 2 and isinstance(node[2], list) else ""
        am = "; ".join(_items_of(node[6])) if len(node) > 6 and isinstance(node[6], list) else ""
        return (svc or None, hl or None, pf or None, am or None)
    except Exception:
        return None, None, None, None


def build_business(rec, cid: str, gid: str = "", is_ad: bool = False) -> "Business":
    def g(*idx):
        cur = rec
        for i in idx:
            try:
                cur = cur[i]
            except (KeyError, IndexError, TypeError):
                return None
        return cur

    name = _strip_quotes(g(11))
    street = _strip_quotes(g(2, 0))
    csz = _strip_quotes(g(2, 1))
    rating = g(4, 7)
    reviews = g(4, 8)
    website_url = _strip_quotes(g(7, 0))
    website_domain = _strip_quotes(g(7, 1))
    lat = g(9, 2)
    lng = g(9, 3)
    cats = g(13)
    tz = _strip_quotes(g(30))
    full = _strip_quotes(g(39) or g(18))
    cid_ = g(10) or cid

    category = ""
    if isinstance(cats, list):
        category = "; ".join(_strip_quotes(str(c)) for c in cats if isinstance(c, str))
    elif isinstance(cats, str):
        category = _strip_quotes(cats)

    blob = json.dumps(rec)
    phone = ""
    m = _PHONE_RE.search(blob)
    if m:
        phone = m.group(0)
    email = ""
    me = _EMAIL_RE.search(blob)
    if me:
        email = me.group(0)

    # place_id: modern format carries it at [227][4] as a "ChIJ..." token.
    pid = g(227, 4)
    if isinstance(pid, str) and pid.startswith("ChIJ"):
        place_id = pid
    else:
        place_id = _extract_place_id(rec)

    hours = _extract_hours(rec)
    popular = _extract_popular_times(rec)
    price_lvl, price_desc = _extract_price(rec)
    menu = _extract_menu(rec)
    closed = _extract_closed(rec)
    svc, hl, pf, am = _extract_attributes(rec)

    return Business(
        cid=cid_,
        name=name or "",
        category=category,
        street=street or "",
        city_state_zip=csz or "",
        full_address=full or "",
        rating=rating,
        reviews_count=reviews,
        website=website_domain or website_url or "",
        phone=phone,
        email=email,
        latitude=lat,
        longitude=lng,
        place_id=place_id,
        gid=gid,
        timezone=tz or "",
        thumbnail=_first_image(rec),
        is_ad=is_ad,
        price_level=price_lvl,
        price_desc=price_desc or "",
        hours=json.dumps(hours, ensure_ascii=False) if hours else "",
        popular_times=json.dumps(popular, ensure_ascii=False) if popular else "",
        menu_url=menu or "",
        closed_status=closed or "",
        amenities=am or "",
        service_options=svc or "",
        highlights=hl or "",
        popular_for=pf or "",
        emails=json.dumps([email] if email else []),
        socials="[]",
        reviews="[]",
        raw_json=json.dumps(rec, ensure_ascii=False),
    )
