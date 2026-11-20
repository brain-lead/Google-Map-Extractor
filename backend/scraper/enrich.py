"""Website enrichment: scrape a business's own website for emails + social profiles.

Google Maps itself almost never exposes a business email or social links, so to
match the "contact enrichment" competitors offer we fetch the company website and
extract emails and social-media profile URLs. Best-effort: any failure yields an
empty result and the caller keeps whatever Maps provided.
"""
import html as html_lib
import re
import threading
from datetime import datetime
from urllib.parse import urlparse, urljoin

from backend.scraper.client import fetch_image  # reuse sync session factory pattern
from backend.scraper.client import Session, IMPERSONATE
from curl_cffi.requests.errors import RequestsError

# Cache domain-age lookups (WHOIS) so re-scoring / repeat crawls are instant.
_DOMAIN_AGE_CACHE: dict = {}


def _lookup_domain_age(domain: str):
    """Best-effort domain age in years via WHOIS. Threaded + timeout-guarded so a
    slow/failing registrar lookup can never hang the enrichment pipeline.
    Returns a float (years) or None."""
    if not domain:
        return None
    if domain in _DOMAIN_AGE_CACHE:
        return _DOMAIN_AGE_CACHE[domain]
    _DOMAIN_AGE_CACHE[domain] = None  # negative-cache to avoid repeated slow lookups
    try:
        import whois as whois_lib
    except Exception:
        return None

    result = {}

    def _do():
        try:
            w = whois_lib.whois(domain)
            cd = getattr(w, "creation_date", None)
            if isinstance(cd, list):
                cd = next((d for d in cd if d), None)
            if isinstance(cd, str):
                try:
                    cd = datetime.strptime(cd[:10], "%Y-%m-%d")
                except Exception:
                    cd = None
            if isinstance(cd, datetime):
                result["age"] = round((datetime.now() - cd).days / 365.25, 1)
        except Exception:
            pass

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(3.0)
    val = result.get("age")
    _DOMAIN_AGE_CACHE[domain] = val
    return val

# Social platforms we care about
_SOCIAL_RE = re.compile(
    r"https?://(?:www\.)?(?:"
    r"facebook\.com/[A-Za-z0-9.\-_/]+"
    r"|instagram\.com/[A-Za-z0-9.\-_/]+"
    r"|linkedin\.com/(?:company|in|school)/[A-Za-z0-9.\-_%/]+"
    r"|twitter\.com/[A-Za-z0-9_]+"
    r"|x\.com/[A-Za-z0-9_]+"
    r"|youtube\.com/(?:@|c/|channel/|user/)?[A-Za-z0-9.\-_]+"
    r"|tiktok\.com/@[A-Za-z0-9.\-_]+"
    r")",
    re.I,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_OBFUSCATED_AT_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\))\s*([A-Za-z0-9.\-]+)\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\))\s*([A-Za-z]{2,})",
    re.I,
)
_EMAIL_IGNORE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".woff", ".ttf")
_EMAIL_IGNORE_DOMAINS = ("sentry.io", "wixpress.com", "example.com")


def _same_or_child(url: str, domain: str) -> bool:
    try:
        h = urlparse(url).netloc.lower()
        base = domain[4:] if domain.startswith("www.") else domain
        return h == base or h.endswith("." + base)
    except Exception:
        return False


def _add_email(emails: set, addr: str) -> None:
    low = addr.strip().lower()
    if any(low.endswith(ext) for ext in _EMAIL_IGNORE_EXT):
        return
    if any(low.endswith("@" + d) or ("." + d) in low for d in _EMAIL_IGNORE_DOMAINS):
        return
    if _EMAIL_RE.fullmatch(low):
        emails.add(low)


def _scrape_html(html: str, emails: set, socials: set) -> None:
    """Scan page HTML for emails (incl. mailto: and simple [at]/[dot]) and social links."""
    if not html:
        return
    for em in _EMAIL_RE.findall(html):
        _add_email(emails, em)
    for m in _OBFUSCATED_AT_RE.finditer(html):
        _add_email(emails, f"{m.group(1)}@{m.group(2)}.{m.group(3)}")
    for m in _SOCIAL_RE.finditer(html):
        socials.add(m.group(0).rstrip("/"))
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
        href = m.group(1)
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0]
            _add_email(emails, addr)
        elif href.startswith("http") and _SOCIAL_RE.match(href):
            socials.add(href.rstrip("/"))


def _find_subpages(html: str, website: str, domain: str, max_links: int = 3):
    """Return absolute URLs of likely contact/about/team pages on the same domain."""
    keys = ("contact", "about", "team", "staff", "company", "support", "info", "reach", "get-in-touch", "kontakt", "impressum")
    found, seen = [], set()
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
        href = m.group(1)
        if not href or href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        low = href.lower()
        if not any(k in low for k in keys):
            continue
        abs_url = urljoin(website, href)
        if not _same_or_child(abs_url, domain):
            continue
        norm = abs_url.rstrip("/")
        if norm in seen or norm == website.rstrip("/"):
            continue
        seen.add(norm)
        found.append(abs_url)
        if len(found) >= max_links:
            break
    return found


# CMS / site-tech signatures detected from already-fetched page HTML.
_CMS_RE = [
    ("wordpress", re.compile(r"(wp-content|wp-includes|/wp-json|wordpress)", re.I)),
    ("woocommerce", re.compile(r"woocommerce", re.I)),
    ("shopify", re.compile(r"(shopify|cdn\.shopify\.com|myshopify\.com)", re.I)),
    ("react", re.compile(r"(react-dom|__NEXT_DATA__|_next/static|reactjs\.org|/static/react)", re.I)),
]
_ANALYTICS_RE = re.compile(r"(google-analytics\.com|gtag\(|gtag\.js|G-[A-Z0-9]{6,}|ua-\d{4,9}-\d{1,4})", re.I)
_PIXEL_RE = re.compile(r"(fbq\(|connect\.facebook\.net|tr\?id=|tr\.id=|facebook\.net/tr)", re.I)
_LIVECHAT_RE = re.compile(
    r"(tawk\.to|intercom\.com|intercom\.io|zendesk\.com|crisp\.chat|drift\.com|livechatinc|jivochat|hubspot\.com/(messenger|conversations)|tidio)", re.I)


def _detect_web(html: str) -> dict:
    """Best-effort website tech profile from already-fetched HTML.

    No extra network requests — everything is derived from the page we already
    downloaded for email/social extraction. `ssl` is filled in by the caller
    from the final response URL (None = unknown / no response).
    """
    out = {
        "ssl": None, "cms": [], "has_contact_form": False,
        "has_livechat": False, "has_analytics": False,
        "has_fb_pixel": False, "has_viewport": False,
    }
    if not html:
        return out
    low = html.lower()
    for name, rx in _CMS_RE:
        if rx.search(html):
            out["cms"].append(name)
    out["has_analytics"] = bool(_ANALYTICS_RE.search(html))
    out["has_fb_pixel"] = bool(_PIXEL_RE.search(html))
    out["has_livechat"] = bool(_LIVECHAT_RE.search(html))
    out["has_contact_form"] = ("<form" in low) or ('type="email"' in low) \
        or ("type='email'" in low) or ("mailto:" in low)
    out["has_viewport"] = "viewport" in low
    return out


def _html_to_text(raw_html: str, limit: int = 1800) -> str:
    """Strip scripts/styles/tags into clean readable text for AI evaluation."""
    if not raw_html:
        return ""
    s = re.sub(r"<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def _get_with_retry(session: Session, url: str, timeout: int, retries: int = 2):
    for i in range(retries):
        try:
            resp = session.get(url, allow_redirects=True, timeout=timeout)
            if resp.status_code == 200 or i == retries - 1:
                return resp
        except RequestsError:
            if i == retries - 1:
                return None
    return None


def enrich_website(website: str, max_bytes: int = 600_000, timeout: int = 15,
                   max_pages: int = 4, include_domain_age: bool = False) -> dict:
    """Fetch a website (plus contact/about/team subpages) with retries & fallbacks."""
    if not website or not website.startswith("http"):
        return {"emails": [], "socials": [], "web": _detect_web("")}
    domain = urlparse(website).netloc.lower()
    secure = website if website.startswith("https") else "https://" + website.split("://", 1)[-1]
    session = Session(
        impersonate=IMPERSONATE,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=timeout,
    )
    emails: set = set()
    socials: set = set()
    web = _detect_web("")
    text_parts: list[str] = []
    try:
        candidates = [secure, "http://" + domain]
        if not domain.startswith("www."):
            candidates.extend(["https://www." + domain, "http://www." + domain])
        resp = None
        for cand in candidates:
            r = _get_with_retry(session, cand, timeout=timeout, retries=2)
            if r is not None and r.status_code == 200:
                resp = r
                break
        if resp is None or resp.status_code != 200:
            return {"emails": [], "socials": [], "web": web, "site_text": ""}
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            web["ssl"] = urlparse(resp.url).scheme == "https"
            return {"emails": [], "socials": [], "web": web, "site_text": ""}
        html = resp.content.decode("utf-8", "replace")[:max_bytes]
        web = _detect_web(html)
        web["ssl"] = urlparse(resp.url).scheme == "https"
        if include_domain_age:
            age = _lookup_domain_age(domain)
            if age is not None:
                web["domain_age"] = age
        _scrape_html(html, emails, socials)
        home_txt = _html_to_text(html, limit=1800)
        if home_txt:
            text_parts.append(f"[Home] {home_txt}")

        for url in _find_subpages(html, str(resp.url), domain, max_links=max_pages - 1):
            r2 = _get_with_retry(session, url, timeout=timeout, retries=2)
            if r2 is None or r2.status_code != 200:
                continue
            c2 = (r2.headers.get("content-type") or "").lower()
            if "html" not in c2 and "text" not in c2:
                continue
            sub_html = r2.content.decode("utf-8", "replace")[:max_bytes]
            _scrape_html(sub_html, emails, socials)
            sub_txt = _html_to_text(sub_html, limit=900)
            if sub_txt:
                path_tag = urlparse(url).path.strip("/") or "subpage"
                text_parts.append(f"[{path_tag}] {sub_txt}")
    finally:
        session.close()

    site_text = "\n".join(text_parts)[:4000]
    return {"emails": sorted(emails), "socials": sorted(socials), "web": web, "site_text": site_text}
