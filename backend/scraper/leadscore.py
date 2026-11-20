"""Configurable, explainable lead scoring for scraped businesses.

Deterministic + offline (no external LLM) so it runs instantly and for free, and
— crucially — it explains *why* a business scores the way it does in plain
language. Each business gets:
  - lead_score : 0-100 (higher = hotter / higher quality, depending on preset)
  - lead_grade : Hot (>=70) / Warm (45-69) / Cold (<45) / Closed
  - lead_reasons : human-readable explanations
  - lead_tags  : machine tags (no_website, low_reviews, chain, ...) for filtering

The engine is data-driven: a set of FACTORS, each of which fires a (reason, tag)
when its condition is met. A PRESET supplies a signed weight per factor (a
positive weight rewards the condition, a negative weight penalizes it). This lets
us ship different "opinions" of a good lead:

  * needs_help  — favours businesses with weak/ missing web presence (web-design,
                  SEO, marketing upsell leads). This is the original behaviour.
  * quality     — favours established, complete-profile businesses (real, have a
                  website/email/social/reviews, older domain, strong rating).
  * custom      — user-edited weights (set in the app Settings tab).

A user picks a preset (or customises) in Settings; the choice is persisted and
applied both to new scrapes and to on-demand "re-score" runs.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from backend.scraper.fields import Business

# National chains / franchises are usually poor fits for one-off web-dev /
# SEO / marketing upsells (decisions are corporate). Flag and down-weight them.
CHAIN_BRANDS = {
    "mcdonald", "mcdonalds", "burger king", "subway", "kfc", "wendy", "wendy's",
    "taco bell", "starbucks", "dunkin", "domino", "domino's", "pizza hut",
    "papa john", "chipotle", "walmart", "target", "costco", "home depot",
    "lowe's", "lowes", "bank of america", "wells fargo", "chase", "citibank",
    "td bank", "us bank", "ups store", "fedex", "7-eleven", "7 eleven", "shell",
    "bp ", "exxon", "chevron", "marriott", "hilton", "holiday inn",
    "comfort inn", "motel 6", "verizon", "at&t", "t-mobile", "sprint",
    "cricket wireless", "dollar general", "dollar tree", "family dollar", "cvs",
    "walgreens", "nike", "adidas", "foot locker", "best buy", "gamestop",
    "autozone", "o'reilly", "napa auto", "jiffy lube", "applebee", "ihop",
    "denny's", "red lobster", "olive garden", "buffalo wild", "popeyes",
}

# Categories that are strong upsell targets for web / SEO / marketing services.
HOT_CATEGORIES = {
    "restaurant", "cafe", "coffee", "bar", "bakery", "pizzeria", "bistro",
    "salon", "spa", "barber", "hair", "nail", "dentist", "dental", "clinic",
    "doctor", "lawyer", "law firm", "attorney", "accountant", "bookkeep",
    "real estate", "realtor", "insurance", "mortgage", "contractor", "plumber",
    "electrician", "hvac", "roofer", "landscap", "handyman", "auto repair",
    "mechanic", "collision", "gym", "fitness", "yoga", "pilates", "photographer",
    "wedding", "event", "cleaning", "maid", "tutor", "daycare", "childcare",
    "pet", "veterinarian", "vet ", "boutique", "jewelry", "florist", "travel",
    "agent", "agency", "consult", "design", "studio", "therapist",
}


def _looks_like_chain(biz: Business) -> bool:
    text = f"{biz.name} {biz.category}".lower()
    return any(brand in text for brand in CHAIN_BRANDS)


def _category_boost(biz: Business) -> int:
    cat = (biz.category or "").lower()
    return 10 if any(c in cat for c in HOT_CATEGORIES) else 0


def _parse(biz: Business):
    import json as _json
    web = {}
    if biz.web_tech:
        try:
            web = _json.loads(biz.web_tech) or {}
        except Exception:
            web = {}
    emails = []
    if biz.emails:
        try:
            emails = _json.loads(biz.emails) or []
        except Exception:
            emails = []
    has_email = bool(biz.email) or bool(emails)
    has_phone = bool(biz.phone)
    has_social = bool(biz.socials and "http" in biz.socials)
    rc = biz.reviews_count or 0
    domain_age = web.get("domain_age")
    return {
        "web": web, "emails": emails, "has_email": has_email,
        "has_phone": has_phone, "has_social": has_social, "rc": rc,
        "domain_age": domain_age,
    }


# --------------------------------------------------------------------------
# Factor registry. Each factor returns (reason, tag) when it applies, else None.
# The sign/magnitude comes from the preset's weight, not from here.
# --------------------------------------------------------------------------
FactorFn = Callable[[Business, dict], Optional[tuple]]


def _f_no_website(b, c):
    return ("No website — prime web-design / SEO lead.", "no_website") if not b.website else None


def _f_no_ssl(b, c):
    return ("Website has no SSL certificate — easy security / upgrade pitch.", "no_ssl") \
        if c["web"].get("ssl") is False else None


def _f_no_contact_form(b, c):
    return ("No contact form on website — lead-generation opportunity.", "no_contact_form") \
        if c["web"].get("has_contact_form") is False else None


def _f_no_contact(b, c):
    return ("No public email or phone — hard to reach; directory/contact-form lead.", "no_contact") \
        if not c["has_email"] and not c["has_phone"] else None


def _f_no_email(b, c):
    return ("No public email found — email-outreach lead.", "no_email") if not c["has_email"] else None


def _f_no_social(b, c):
    return ("No social profiles — social-media management lead.", "no_social") if not c["has_social"] else None


def _f_no_reviews(b, c):
    return ("Zero reviews — brand-new or unmanaged listing (early opportunity).", "no_reviews") if c["rc"] == 0 else None


def _f_low_reviews(b, c):
    return (f"Only {c['rc']} reviews — young / under-managed listing.", "low_reviews") if 0 < c["rc"] < 15 else None


def _f_many_reviews(b, c):
    return ("Established listing with high review volume.", "established") if c["rc"] > 200 else None


def _f_low_rating(b, c):
    return (f"Low {b.rating}★ with real volume — reputation-management lead.", "low_rating") \
        if (b.rating is not None and b.rating < 3.5 and c["rc"] >= 15) else None


def _f_thin_profile(b, c):
    return ("No published hours — thin Google Business Profile.", "thin_profile") if not b.hours else None


def _f_chain(b, c):
    return ("Likely a national chain/franchise — usually not a fit for one-off services.", "chain") \
        if _looks_like_chain(b) else None


def _f_category_fit(b, c):
    return ("Category is a strong fit for web / SEO / marketing services.", "category_fit") if _category_boost(b) else None


def _f_runs_ads(b, c):
    return ("Already running Google Ads — values marketing; retainer candidate.", "runs_ads") if b.is_ad else None


def _f_has_website(b, c):
    return ("Has a website — established online presence.", "has_website") if b.website else None


def _f_has_email(b, c):
    return ("Public email available — easy to reach.", "has_email") if c["has_email"] else None


def _f_has_social(b, c):
    return ("Active social profiles — engaged brand.", "has_social") if c["has_social"] else None


def _f_has_reviews(b, c):
    return (f"{c['rc']} reviews — proven track record.", "has_reviews") if c["rc"] >= 15 else None


def _f_high_rating(b, c):
    return (f"Strong {b.rating}★ rating — reputable business.", "high_rating") \
        if (b.rating is not None and b.rating >= 4.0) else None


def _f_established(b, c):
    da = c.get("domain_age")
    return (f"Domain ~{round(da, 1)} yrs old — established business.", "established") \
        if (da is not None and da >= 5) else None


def _f_has_contact_form_p(b, c):
    return ("Has a contact form — converts well.", "has_contact_form_p") \
        if c["web"].get("has_contact_form") is True else None


def _f_has_ssl_p(b, c):
    return ("Site is SSL-secured — professional.", "has_ssl_p") if c["web"].get("ssl") is True else None


FACTORS: dict[str, FactorFn] = {
    "no_website": _f_no_website,
    "no_ssl": _f_no_ssl,
    "no_contact_form": _f_no_contact_form,
    "no_contact": _f_no_contact,
    "no_email": _f_no_email,
    "no_social": _f_no_social,
    "no_reviews": _f_no_reviews,
    "low_reviews": _f_low_reviews,
    "many_reviews": _f_many_reviews,
    "low_rating": _f_low_rating,
    "thin_profile": _f_thin_profile,
    "chain": _f_chain,
    "category_fit": _f_category_fit,
    "runs_ads": _f_runs_ads,
    "has_website": _f_has_website,
    "has_email": _f_has_email,
    "has_social": _f_has_social,
    "has_reviews": _f_has_reviews,
    "high_rating": _f_high_rating,
    "established": _f_established,
    "has_contact_form_p": _f_has_contact_form_p,
    "has_ssl_p": _f_has_ssl_p,
}

# Human-readable labels for the Settings UI sliders (ordered for display).
FACTOR_META = [
    ("no_website", "Missing website"),
    ("no_ssl", "No SSL certificate"),
    ("no_contact_form", "No contact form"),
    ("no_contact", "No email & no phone"),
    ("no_email", "Missing email"),
    ("no_social", "Missing socials"),
    ("no_reviews", "Zero reviews"),
    ("low_reviews", "Few reviews (<15)"),
    ("low_rating", "Low rating (<3.5★)"),
    ("thin_profile", "Thin profile (no hours)"),
    ("chain", "National chain/franchise"),
    ("category_fit", "Category fit (web/SEO)"),
    ("runs_ads", "Already runs ads"),
    ("has_website", "Has website"),
    ("has_email", "Has email"),
    ("has_social", "Has socials"),
    ("has_reviews", "Has reviews (≥15)"),
    ("high_rating", "Strong rating (≥4.0★)"),
    ("established", "Established (old domain)"),
    ("has_contact_form_p", "Has contact form"),
    ("has_ssl_p", "SSL-secured"),
]

# --------------------------------------------------------------------------
# Presets: signed weights per factor. Positive = reward when condition fires,
# negative = penalise. baseline = neutral starting score.
# --------------------------------------------------------------------------
PRESETS = {
    "needs_help": {
        "label": "Needs Help (upsell)",
        "baseline": 50,
        "use_domain_age": False,
        "weights": {
            "no_website": 25, "no_ssl": 8, "no_contact_form": 5, "no_contact": 12,
            "no_email": 6, "no_social": 6, "no_reviews": 10, "low_reviews": 6,
            "many_reviews": -4, "low_rating": 6, "thin_profile": 4, "chain": -30,
            "category_fit": 10, "runs_ads": 3,
        },
    },
    "quality": {
        "label": "Quality / Establishment",
        "baseline": 50,
        "use_domain_age": True,
        "weights": {
            "has_website": 20, "has_email": 10, "has_social": 8, "has_reviews": 10,
            "high_rating": 8, "established": 15, "has_contact_form_p": 4, "has_ssl_p": 4,
            "category_fit": 5, "many_reviews": 4,
            "no_website": -20, "no_email": -10, "no_social": -8, "no_reviews": -10,
            "low_rating": -6, "thin_profile": -8, "chain": 0,
        },
    },
}

DEFAULT_SCORING = {"preset": "needs_help"}


@dataclass
class ScoreResult:
    score: int = 0
    grade: str = "Cold"
    reasons: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


def resolve_config(scoring: Optional[dict] = None) -> dict:
    """Merge a stored scoring choice with preset defaults into an effective config.

    Returns {preset, baseline, use_domain_age, weights}. For the 'custom' preset
    the stored weights override the base preset's weights.
    """
    scoring = scoring or {}
    preset = scoring.get("preset", "needs_help")
    if preset not in PRESETS and preset != "custom":
        preset = "needs_help"
    base = PRESETS.get(preset, PRESETS["needs_help"])
    weights = {k: float(v) for k, v in base["weights"].items()}
    baseline = float(scoring.get("baseline", base.get("baseline", 50)))
    use_domain_age = bool(scoring.get("use_domain_age", base.get("use_domain_age", False)))
    if preset == "custom":
        for k, v in (scoring.get("weights") or {}).items():
            if k in FACTORS:
                weights[k] = float(v)
    if not use_domain_age:
        weights["established"] = 0.0
    return {
        "preset": preset,
        "baseline": baseline,
        "use_domain_age": use_domain_age,
        "weights": weights,
    }


class _Row:
    """Lightweight adapter so a raw DB row (dict) can be scored without building
    a full Business dataclass."""

    def __init__(self, d: dict):
        self.name = d.get("name")
        self.category = d.get("category")
        self.website = d.get("website") or ""
        self.web_tech = d.get("web_tech")
        self.emails = d.get("emails")
        self.email = d.get("email") or ""
        self.phone = d.get("phone") or ""
        self.socials = d.get("socials")
        self.reviews_count = d.get("reviews_count") or 0
        self.rating = d.get("rating")
        self.hours = d.get("hours")
        self.is_ad = d.get("is_ad")
        self.closed_status = d.get("closed_status")


def score_row(row: dict, config: Optional[dict] = None) -> ScoreResult:
    """Score a raw result dict (as stored in the DB)."""
    return score_business(_Row(row), config)


def score_business(biz: Business, config: Optional[dict] = None) -> ScoreResult:
    """Return an explainable lead score for one business."""
    cfg = config or resolve_config(DEFAULT_SCORING)
    weights = cfg.get("weights", {})

    # --- Hard disqualifier (always wins, regardless of preset) ---
    if biz.closed_status:
        return ScoreResult(0, "Closed",
                           [f"{biz.closed_status} — not a live opportunity."], ["closed"])

    c = _parse(biz)
    score = float(cfg.get("baseline", 50))
    reasons: List[str] = []
    tags: List[str] = []

    for fid, fn in FACTORS.items():
        w = weights.get(fid, 0.0)
        if not w:
            continue
        r = fn(biz, c)
        if r:
            reason, tag = r
            score += w
            reasons.append(reason)
            if tag not in tags:
                tags.append(tag)

    score = max(0, min(100, int(round(score))))
    grade = "Hot" if score >= 70 else ("Warm" if score >= 45 else "Cold")
    return ScoreResult(score=score, grade=grade, reasons=reasons, tags=tags)
