"""Reviews endpoint: /maps/preview/review/listentitiesreviews -> review text.

Google's main details endpoint (j[6]) carries review *rating/count* but not the
review text/author. The dedicated reviews endpoint does. The pb format for that
endpoint has drifted and isn't captured in our Burp exports, so this is a
best-effort implementation: if it parses, we return reviews; on any failure we
return an empty list and the caller keeps the rating/count it already has.
"""
import asyncio
import json
import re
from backend.scraper.client import make_session, get_json, strip_xssi, BASE, StaleSessionError
from backend.scraper import pb as _pb


def build_reviews_pb(place_id: str) -> str:
    pid = place_id.replace("ChIJ", "") if place_id.startswith("ChIJ") else place_id
    return (
        "!1m2!1sChIJ" + pid + "!2s0"
        "!3e1!4m5!3e1!4m4!1i10!2i10!3i10"
        "!5m2!1s!2s"
    )


_REVIEW_TEXT_RE = re.compile(r"[A-Za-z]{4,}")


def _looks_like_review(node) -> dict | None:
    """Heuristically identify a review object inside the response tree."""
    if not isinstance(node, list) or len(node) < 6:
        return None
    author = None
    rating = None
    text = None
    rel_time = None
    for v in node:
        if isinstance(v, str):
            # author name: short-ish, mostly letters, not a url/token
            if (author is None and 2 <= len(v) <= 40
                    and v.replace(" ", "").isalpha() and " " in v):
                author = v
            # relative time e.g. "a day ago", "3 weeks ago"
            elif rel_time is None and re.search(r"\b(ago|week|month|year|day|hour)\b", v, re.I):
                rel_time = v
            # review text: a longer readable string
            elif text is None and len(v) > 25 and _REVIEW_TEXT_RE.search(v):
                text = v
        elif isinstance(v, (int, float)):
            if rating is None and 1 <= v <= 5:
                rating = int(v)
            elif rating is None and 10 <= v <= 50:
                rating = int(round(v / 2))  # stored x2 in some layouts
    if (author or text) and (rating or text):
        blob = json.dumps(node, ensure_ascii=False).lower() if len(node) > 6 else ""
        has_owner_reply = ("response from the owner" in blob) or ("owner" in blob and len(blob) > 200)
        return {
            "author": author or "",
            "rating": rating,
            "text": text or "",
            "time": rel_time or "",
            "has_owner_reply": has_owner_reply,
        }
    return None


def _walk_reviews(o, out, depth=0):
    if depth > 30 or len(out) >= 30:
        return
    if isinstance(o, list):
        r = _looks_like_review(o)
        if r and r not in out:
            out.append(r)
        for v in o:
            _walk_reviews(v, out, depth + 1)
    elif isinstance(o, dict):
        for v in o.values():
            _walk_reviews(v, out, depth + 1)


async def fetch_reviews(place_id: str, gl: str = "us", hl: str = "en",
                        cookies: dict | None = None, proxies: str | None = None,
                        tries: int = 2) -> list:
    if not place_id or not place_id.startswith("ChIJ"):
        return []
    p = build_reviews_pb(place_id)
    url = f"{BASE}/maps/preview/review/listentitiesreviews?authuser=0&hl={hl}&gl={gl}&pb={p}"
    for attempt in range(tries):
        session = make_session(cookies=cookies, proxies=proxies)
        try:
            body, ok = await get_json(session, url, referer=f"{BASE}/maps")
            if not ok or body.lstrip()[:1] == b"<":
                if attempt < tries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return []
            try:
                data = json.loads(strip_xssi(body))
            except Exception:
                return []
            out = []
            _walk_reviews(data, out)
            seen = set()
            uniq = []
            for r in out:
                key = (r.get("author"), r.get("text"))
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(r)
            return uniq[:30]
        except StaleSessionError:
            raise
        except Exception:
            if attempt < tries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            return []
        finally:
            await session.close()
    return []
