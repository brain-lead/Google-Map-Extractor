"""Cookie store (Fernet-encrypted) + validation + expiry detection.

The Google endpoints are gated by a logged-in session. We store cookies
encrypted at rest, attach them to every request, and detect when they go
stale (consent page / empty stub response).
"""
import json
import re
import time
import base64
import os
import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
from backend.config import COOKIES_FILE, encrypt_bytes, decrypt_bytes, BASE_DIR
from backend.scraper.client import test_request

# Default BurpSuite capture that ships with the project (source of "default" cookies)
CAPTURE_PATH = BASE_DIR / "requests"

STATUS_FILE = COOKIES_FILE.with_suffix(".status.json")


def _load_raw() -> dict | None:
    if not COOKIES_FILE.exists():
        return None
    try:
        return json.loads(decrypt_bytes(COOKIES_FILE.read_bytes()))
    except Exception:
        return None


def _save_raw(cookies: dict) -> None:
    COOKIES_FILE.write_bytes(encrypt_bytes(json.dumps(cookies).encode()))


def parse_cookie_input(text: str) -> dict:
    """Accept: 'Cookie: a=b; c=d', raw 'a=b; c=d', JSON list [{name,value}],
    or JSON dict."""
    text = text.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    text = text.strip()
    # JSON list / dict
    if text.startswith("["):
        arr = json.loads(text)
        out = {}
        for item in arr:
            if isinstance(item, dict) and "name" in item:
                out[item["name"]] = item.get("value", "")
        return out
    if text.startswith("{"):
        return json.loads(text)
    # header string
    out = {}
    for part in text.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def save_cookies(text: str) -> dict:
    cookies = parse_cookie_input(text)
    _save_raw(cookies)
    ok, reason = validate_cookies(cookies)
    _write_status({"valid": ok, "reason": reason,
                   "count": len(cookies), "last_checked": time.time()})
    return {"valid": ok, "reason": reason, "count": len(cookies)}


def load_cookies() -> dict:
    return _load_raw() or {}


def clear_cookies() -> dict:
    """Delete stored cookies and reset status to anonymous mode."""
    for p in (COOKIES_FILE, STATUS_FILE):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    return {"valid": False, "reason": "cleared (anonymous)", "count": 0, "last_checked": None}


def cookie_status() -> dict:
    cookies = load_cookies()
    if not cookies:
        return {"valid": False, "reason": "no cookies stored", "count": 0,
                "last_checked": None}
    status = {}
    if STATUS_FILE.exists():
        try:
            status = json.loads(STATUS_FILE.read_text())
        except Exception:
            status = {}
    return {"valid": status.get("valid", False),
            "reason": status.get("reason", "unknown"),
            "count": len(cookies),
            "last_checked": status.get("last_checked")}


def _write_status(d: dict) -> None:
    STATUS_FILE.write_text(json.dumps(d))


def validate_cookies(cookies: dict | None = None) -> tuple[bool, str]:
    """Fire a lightweight request; valid if 200 + real JSON (not a stub)."""
    cookies = cookies if cookies is not None else load_cookies()
    if not cookies:
        return False, "no cookies"
    try:
        body, ok = test_request(cookies)
    except Exception as e:  # network / blocked
        return False, f"request failed: {e}"
    if not ok:
        return False, "request returned non-200 / blocked"
    # A real suggest/search response is a JSON array; a stub is tiny / HTML.
    try:
        import json as _json
        data = _json.loads(body)
        if isinstance(data, list) and len(data) >= 1:
            return True, "ok"
    except Exception:
        pass
    if len(body) < 5000:
        return False, "stub/consent response (cookies likely expired)"
    return False, "unexpected response shape"


def mark_stale(reason: str) -> None:
    _write_status({"valid": False, "reason": reason,
                   "count": len(load_cookies()), "last_checked": time.time()})


def _extract_cookie_from_capture(src: Path) -> str | None:
    """Pull the first Google `Cookie:` header out of a BurpSuite XML export."""
    if not src or not src.exists():
        return None
    try:
        ctx = ET.iterparse(str(src), events=("end",))
        for ev, elem in ctx:
            if ev != "end" or elem.tag.split("}", 1)[-1] != "item":
                continue
            host = ""; req_b64 = False; raw = b""
            for c in elem:
                n = c.tag.split("}", 1)[-1]
                if n == "host":
                    host = (c.text or "").strip()
                elif n == "request":
                    req_b64 = (c.attrib.get("base64") == "true")
                    txt = c.text or ""
                    try:
                        raw = base64.b64decode(txt) if req_b64 else txt.encode()
                    except Exception:
                        raw = b""
            if "google" in host:
                m = re.search(r"(?im)^Cookie:\s*(.*?)\r?$", raw.decode("utf-8", "ignore"))
                if m:
                    elem.clear()
                    return m.group(1).strip()
            elem.clear()
    except Exception:
        return None
    return None


def import_from_capture(src: str | None = None) -> dict:
    """Extract Google cookies from the capture file and store them (encrypted)."""
    path = Path(src) if src else CAPTURE_PATH
    cookie_str = _extract_cookie_from_capture(path)
    if not cookie_str:
        return {"imported": False, "reason": "no google Cookie header found in capture"}
    cookies = parse_cookie_input(cookie_str)
    _save_raw(cookies)
    ok, reason = validate_cookies(cookies)
    _write_status({"valid": ok, "reason": reason, "count": len(cookies),
                   "last_checked": time.time(), "source": "capture"})
    return {"imported": True, "valid": ok, "reason": reason, "count": len(cookies)}


async def auto_generate_visitor_cookies(proxy: str | None = None) -> dict:
    """Fetch fresh *visitor* cookies from Google (no login required).

    Google Maps search works with these anonymous/visitor cookies, so this is
    a real "auto cookie" path: the app self-acquires working cookies on startup
    or whenever the stored set goes stale — no manual paste, no account.
    """
    from backend.scraper.client import make_session, BASE, base_headers
    session = make_session(cookies={}, proxies=proxy)
    try:
        await session.get(BASE + "/maps", headers=base_headers())
        cookies = {k: v for k, v in session.cookies.items()}
    finally:
        await session.close()
    if not cookies:
        return {"generated": False, "reason": "Google returned no cookies"}
    _save_raw(cookies)
    ok, reason = validate_cookies(cookies)
    _write_status({"valid": ok, "reason": reason, "count": len(cookies),
                   "last_checked": time.time(), "source": "auto-generated"})
    return {"generated": True, "valid": ok, "reason": reason, "count": len(cookies)}


def is_session_stale(max_age_seconds: int = 6 * 3600) -> bool:
    """True when cookies are missing, marked invalid, or older than max_age_seconds."""
    if not COOKIES_FILE.exists() or not load_cookies():
        return True
    st = cookie_status()
    if not st.get("valid"):
        return True
    checked = st.get("last_checked") or 0
    return (time.time() - checked) > max_age_seconds


def ensure_default_cookies(src: str | None = None) -> bool:
    """Seed or refresh cookies automatically if missing or stale."""
    if os.getenv("GMAP_DISABLE_CAPTURE_SEED"):
        return False
    if not is_session_stale(max_age_seconds=12 * 3600):
        return False
    try:
        if asyncio.run(auto_generate_visitor_cookies()).get("generated"):
            return True
    except Exception:
        pass
    if not COOKIES_FILE.exists():
        return bool(import_from_capture(src).get("imported"))
    return False


async def refresh_cookies(src: str | None = None, proxy: str | None = None) -> dict:
    """Attempt to (re)acquire cookies when the current set is expired/stale.

    Prefers freshly auto-generated visitor cookies (trying direct first, then
    an active proxy if supplied) before falling back to the bundled capture.
    """
    for p in ([None, proxy] if proxy else [None]):
        try:
            res = await auto_generate_visitor_cookies(proxy=p)
            if res.get("generated"):
                res["refreshed"] = True
                return res
        except Exception:
            pass
    res = import_from_capture(src)
    res["refreshed"] = True
    return res
