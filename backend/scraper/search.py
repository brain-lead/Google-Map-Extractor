"""Search endpoint: tbm=map -> list of business leads (organic + ads).

The modern Google Maps response is a wrapped/direct JSON array whose business
"cards" live in the directory at index 64 (a list of result groups; each group
holds one card). Every card already carries the full record (name, CID, coords,
rating, reviews, category, address, phone, timezone, place_id), so we feed each
card straight into fields.build_business. See research/06_findings/captured_pb.txt
and the unauthenticated capture analysis for the verified field indices.
"""
import json
import logging
import re
from backend.config import DATA_DIR
from backend.scraper import pb
from backend.scraper.client import make_session, get_json, strip_xssi, BASE, StaleSessionError
from backend.scraper import fields


# ---- Diagnostic logger (non-destructive; for count investigation) ----
_diag = logging.getLogger("search_diag")
if not _diag.handlers:
    try:
        _dh = logging.FileHandler(DATA_DIR / "search_diag.log", encoding="utf-8")
        _dh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        _diag.addHandler(_dh)
        _diag.setLevel(logging.INFO)
        _diag.propagate = False
    except Exception:
        pass

CID_RE = re.compile(r"^0x[0-9a-f]+:0x[0-9a-fA-F]+$")

# Pagination seed token embedded in SEARCH_PB (the leading !22m5 cursor). To
# fetch the next page we swap this token with the continuation token Google
# returns in the response. IMPORTANT: the old code inserted a *second* !22m
# cursor, which made Google ignore it and re-serve page 1 (so every search
# was capped at a single page). The !15i<...> index is ignored by Google.
SEED_TOKEN = "gMJMaqjYGITqhbIP58nQmQ0"
assert SEED_TOKEN in pb.SEARCH_PB, "SEED_TOKEN drifted from pb.SEARCH_PB"


def _unwrap(data):
    """Newer responses wrap the array as {"c":0,"d":"...)]\n[[...]]"}."""
    if isinstance(data, dict) and isinstance(data.get("d"), str):
        d = data["d"]
        if d.startswith(")]}'"):
            i = d.find("\n")
            d = d[i + 1:] if i != -1 else d
        try:
            return json.loads(d)
        except Exception:
            return data
    return data


def _first_cid(x, depth=0):
    if depth > 8:
        return None
    if isinstance(x, str) and CID_RE.match(x):
        return x
    if isinstance(x, list):
        for v in x:
            r = _first_cid(v, depth + 1)
            if r:
                return r
    elif isinstance(x, dict):
        for v in x.values():
            r = _first_cid(v, depth + 1)
            if r:
                return r
    return None


def _first_coord(x, depth=0):
    if depth > 8:
        return None
    if isinstance(x, list) and len(x) >= 4 and x[0] is None and x[1] is None \
       and isinstance(x[2], (int, float)) and isinstance(x[3], (int, float)):
        return x
    if isinstance(x, list):
        for v in x:
            r = _first_coord(v, depth + 1)
            if r:
                return r
    elif isinstance(x, dict):
        for v in x.values():
            r = _first_coord(v, depth + 1)
            if r:
                return r
    return None


def _count_all_cards(o, depth=0):
    """Count every card-shaped list in the whole document (ignores the
    one-per-group walk) — used only for diagnostics to detect under-counting."""
    if depth > 22:
        return 0
    n = 0
    if isinstance(o, list) and len(o) > 40:
        cid = o[10] if len(o) > 10 else None
        name = o[11] if len(o) > 11 else None
        if isinstance(cid, str) and CID_RE.match(cid) and isinstance(name, str) \
           and _first_coord(o):
            n += 1
    if isinstance(o, list):
        for v in o:
            n += _count_all_cards(v, depth + 1)
    elif isinstance(o, dict):
        for v in o.values():
            n += _count_all_cards(v, depth + 1)
    return n


def _find_card(x, depth=0):
    if depth > 22:
        return None
    # Require the standard-layout card: a real 0x..:0x.. CID at [10] and a
    # name string at [11]. This avoids "featured"/ad cards that carry the CID
    # deeper and leave [10]/[11] empty or as a token.
    if isinstance(x, list) and len(x) > 40:
        cid = x[10] if len(x) > 10 else None
        name = x[11] if len(x) > 11 else None
        if isinstance(cid, str) and CID_RE.match(cid) and isinstance(name, str) \
           and _first_coord(x):
            return x
    if isinstance(x, list):
        for v in x:
            r = _find_card(v, depth + 1)
            if r is not None:
                return r
    elif isinstance(x, dict):
        for v in x.values():
            r = _find_card(v, depth + 1)
            if r is not None:
                return r
    return None


def parse_search_response(data: list) -> tuple[list, list]:
    arr = _unwrap(data)
    if not isinstance(arr, list):
        return [], []
    # Directory of result cards. Modern format: arr[64] (result groups).
    groups = arr[64] if (len(arr) > 64 and isinstance(arr[64], list)) else [arr]
    cards, seen = [], set()
    for g in groups:
        card = _find_card(g)
        if card is None:
            continue
        cid = _first_cid(card)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        cards.append(card)
    if not cards:  # last-resort whole-document scan
        card = _find_card(arr)
        if card is not None:
            cid = _first_cid(card)
            if cid and cid not in seen:
                cards.append(card)
    organic = [fields.build_business(c, cid=_first_cid(c) or "") for c in cards]
    return [b.to_row() for b in organic], []


TOKEN_RE = re.compile(r"^(?:[A-Za-z0-9_\-]{4,20}_[A-Za-z0-9_\-]{4,30}|[A-Za-z0-9_\-]{14,40})$")
# substrings that indicate a false-positive "token" (photo refs, place ids, words)
_TOKEN_STOP = ("GEO_PHOTO", "from_the_business", "search", "results", "injection",
               "categorical", "review", "partner", "business", "the_", "CIAB", "ChIJ")


def _looks_like_token(s: str) -> bool:
    if not isinstance(s, str) or not TOKEN_RE.match(s):
        return False
    if any(bad in s for bad in _TOKEN_STOP):
        return False
    if s.islower() or s.isupper():  # require mixed case (random token), not a word
        return False
    return True


def extract_continue_token(data) -> str | None:
    if len(data) > 7 and isinstance(data[7], str) and _looks_like_token(data[7]):
        return data[7]
    try:
        v = data[0][1][8]
        if isinstance(v, str) and _looks_like_token(v):
            return v
    except Exception:
        pass
    found = []
    def walk(o, d=0):
        if d > 25:
            return
        if isinstance(o, str):
            if _looks_like_token(o):
                found.append(o)
        elif isinstance(o, list):
            for v in o:
                walk(v, d + 1)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v, d + 1)
    walk(data)
    seen = set()
    for t in found:
        if t not in seen:
            seen.add(t)
            return t
    return None


MAX_PAGES = 15


async def _fetch_page_with_retry(session, url: str, referer: str, tries: int = 3) -> tuple[bytes, bool]:
    """Retry transient per-page HTTP/network errors inside pagination without losing earlier pages."""
    import asyncio
    last_err = None
    for i in range(tries):
        try:
            body, ok = await get_json(session, url, referer=referer)
            if ok:
                return body, True
            last_err = RuntimeError("non-200 response")
        except StaleSessionError:
            raise
        except Exception as e:
            last_err = e
        if i < tries - 1:
            await asyncio.sleep(1.0 * (i + 1))
    if last_err:
        raise last_err
    return b"", False


async def search(query: str, gl: str = "us", hl: str = "en",
                  cookies: dict | None = None, proxies: str | None = None,
                  max_results: int = 100) -> tuple[list, list]:
    """Search Google Maps and walk through result pages until `max_results`
    businesses are collected (or Google stops returning new ones).
    """
    session = make_session(cookies=cookies, proxies=proxies)
    try:
        q = query.replace(" ", "+")
        seen: set = set()
        collected: list = []
        p = pb.SEARCH_PB.replace(pb.SEARCH_QUERY_TOKEN, "!1s" + q)
        cur_token = SEED_TOKEN
        url = f"{BASE}/search?tbm=map&authuser=0&hl={hl}&gl={gl}&q={q}&pb={p}"
        referer = f"https://www.google.com/maps/search/{q}"
        pages = 0
        stop_reason = "loop-end"
        _diag.info("SEARCH START q=%r gl=%s hl=%s max_results=%s proxies=%s",
                   query, gl, hl, max_results, bool(proxies))
        while len(collected) < max_results and pages < MAX_PAGES:
            try:
                body, ok = await _fetch_page_with_retry(session, url, referer=referer)
            except StaleSessionError:
                if collected:
                    _diag.warning("Session block mid-pagination for q=%r after %d leads; returning partial", query, len(collected))
                    stop_reason = "mid-page-block-partial"
                    break
                raise
            except Exception as e:
                if collected:
                    _diag.warning("Page %d failed for q=%r (%s); returning %d partial leads", pages + 1, query, e, len(collected))
                    stop_reason = "mid-page-err-partial"
                    break
                raise
            if not ok:
                stop_reason = "http-not-ok"
                break
            if body.lstrip()[:1] == b"<":
                _diag.warning("HTML block/consent page for q=%r (len=%d)", query, len(body))
                if collected:
                    stop_reason = "mid-page-html-partial"
                    break
                raise StaleSessionError("Google returned HTML consent/block page")
            try:
                data = json.loads(strip_xssi(body))
                if isinstance(data, dict) and isinstance(data.get("d"), str):
                    d = data["d"]
                    if d.startswith(")]}'"):
                        d = d[d.find("\n") + 1:]
                    data = json.loads(d)
                arr = _unwrap(data)
                groups = arr[64] if (isinstance(arr, list) and len(arr) > 64
                                      and isinstance(arr[64], list)) else []
                organic, _ = parse_search_response(data)
            except Exception:
                import traceback as _tb
                with open(DATA_DIR / "search_err.log", "a", encoding="utf-8") as _f:
                    _f.write("=== search parse error ===\n")
                    _tb.print_exc(file=_f)
                    _f.write(f"body repr={repr(body[:400])}\n")
                break
            added = 0
            for row in organic:
                if not isinstance(row, dict):
                    import traceback as _tb2
                    with open(DATA_DIR / "search_err.log", "a", encoding="utf-8") as _f:
                        _f.write("=== non-dict row ===\n")
                        _tb2.print_exc(file=_f)
                        _f.write(f"row type={type(row)} repr={repr(row)[:300]}\n")
                    continue
                cid = row.get("cid")
                if cid and cid not in seen:
                    seen.add(cid)
                    collected.append(row)
                    added += 1
            pages += 1
            # Prepare the next page: swap the current cursor token with the
            # continuation token Google returned. If the token loops back to the
            # same page (added == 0) or there is none, stop gracefully.
            token = extract_continue_token(data)
            _diag.info("PAGE %d q=%r groups=%d cards_1pergroup=%d cards_fulltree=%d "
                       "added=%d collected=%d token=%s",
                       pages, query, len(groups), len(organic), _count_all_cards(data),
                       added, len(collected),
                       ("len=%d" % len(token)) if token else "NONE")
            if len(collected) >= max_results:
                stop_reason = "max_results-reached"
                break
            if not token or added == 0:
                stop_reason = "no-token" if not token else "no-new-results(added==0)"
                break
            p = p.replace(cur_token, token)
            cur_token = token
            url = f"{BASE}/search?tbm=map&authuser=0&hl={hl}&gl={gl}&q={q}&pb={p}"
        _diag.info("SEARCH END q=%r collected=%d pages=%d stop=%s",
                   query, len(collected), pages, stop_reason)
        return collected[:max_results], []
    finally:
        await session.close()
