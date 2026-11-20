"""curl_cffi async HTTP client for Google Maps endpoints.

Wraps session creation, headers, cookie attachment, proxy support, and the
XSSI-prefix stripping Google puts in front of its JSON responses.
"""
from curl_cffi import AsyncSession, Session
from curl_cffi.requests.errors import RequestsError
from backend.config import IMPERSONATE, base_headers
import json

BASE = "https://www.google.com"

HEADERS_SEARCH = base_headers("https://www.google.com/maps/search/__Q__")
HEADERS_DETAILS = base_headers("https://www.google.com/maps")

_BLOCK_MARKERS = (
    b"/sorry/",
    b"unusual traffic",
    b"our systems have detected",
    b"not a robot",
    b"consent.google",
)


class StaleSessionError(RuntimeError):
    """Raised when Google returns a block, rate-limit, or HTML consent stub."""


def is_block_response(status_code: int, body: bytes) -> bool:
    if status_code in (401, 403, 429, 503):
        return True
    head = body.lstrip()[:4096].lower()
    if head.startswith(b"<") and any(m in head for m in _BLOCK_MARKERS):
        return True
    return False


def _proxy_args(proxies):
    """curl_cffi's `proxies` param must be a dict ({scheme: url}); a bare string
    URL belongs in the `proxy` param. Passing a string to `proxies=` made
    set_curl_options call `.get()` on the string -> 'str' object has no attribute
    'get'."""
    if not proxies:
        return None, None
    if isinstance(proxies, str):
        return proxies, None
    return None, proxies


def make_session(cookies: dict | None = None, proxies: str | None = None) -> AsyncSession:
    proxy, proxies_arg = _proxy_args(proxies)
    return AsyncSession(
        impersonate=IMPERSONATE,
        headers=base_headers(),
        cookies=cookies or {},
        proxy=proxy,
        proxies=proxies_arg,
        timeout=30,
    )


async def get_json(session: AsyncSession, url: str, referer: str | None = None,
                  headers: dict | None = None) -> tuple[bytes, bool]:
    """GET a Google endpoint, return (body_bytes, ok). Raises StaleSessionError
    on HTTP 403/429/503 or HTML consent/CAPTCHA pages so callers can refresh session."""
    h = dict(headers or {})
    if referer:
        h["Referer"] = referer
    try:
        resp = await session.get(url, headers=h)
    except RequestsError as e:
        raise RuntimeError(f"request error: {e}")
    if is_block_response(resp.status_code, resp.content):
        raise StaleSessionError(f"blocked or stale session (HTTP {resp.status_code})")
    ok = resp.status_code == 200
    return resp.content, ok


def strip_xssi(body: bytes) -> str:
    """Remove the )]}' XSSI prefix Google prepends to JSON arrays/objects."""
    if body.startswith(b")]}'"):
        # find first newline after prefix
        idx = body.find(b"\n")
        if idx != -1:
            return body[idx + 1:].decode("utf-8", "replace")
    return body.decode("utf-8", "replace")


def test_request(cookies: dict, proxies: str | None = None) -> tuple[str, bool]:
    """Lightweight authenticated probe used to validate cookies (sync)."""
    from backend.scraper import pb
    proxy, proxies_arg = _proxy_args(proxies)
    session = Session(
        impersonate=IMPERSONATE,
        headers=base_headers(),
        cookies=cookies or {},
        proxy=proxy,
        proxies=proxies_arg,
        timeout=30,
    )
    url = (f"{BASE}/search?tbm=map&authuser=0&hl=en&gl=us"
           f"&q=test&pb={pb.SEARCH_PB}")
    try:
        resp = session.get(url, headers={"Referer": "https://www.google.com/maps"})
    except RequestsError as e:
        return "", False
    ok = resp.status_code == 200
    return strip_xssi(resp.content) if ok else "", ok


def fetch_image(url: str, referer: str = "https://www.google.com/maps") -> tuple[bytes, str]:
    """Fetch an image (e.g. a Google Maps business thumbnail) server-side.

    Google's `/a/...` profile-photo CDN URLs are hotlink-protected and get
    blocked when a browser loads them cross-origin from localhost. Proxying
    through our own backend (with a Google Referer) reliably returns the bytes
    from our own origin, so they always render.
    """
    session = Session(
        impersonate=IMPERSONATE,
        headers={"Referer": referer, "Accept": "image/avif,image/webp,image/*,*/*"},
        timeout=20,
    )
    try:
        resp = session.get(url)
    except RequestsError:
        return b"", ""
    if resp.status_code != 200:
        return b"", ""
    return resp.content, resp.headers.get("content-type") or "image/jpeg"
