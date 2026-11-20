"""Goal-driven AI modes, starter missions, and prompt builders."""
import json

BUILTIN_MODES = {
    "web_seo": {
        "id": "web_seo",
        "label": "Web Design & SEO Agency",
        "short": "Website gaps, SSL, pixels, redesign & SEO pitch",
        "focus": (
            "Evaluate the business for Web Design, Website Redesign, Local SEO, SSL/Performance, "
            "or Conversion Tracking services. Look closely at whether they have no website, an outdated/thin site, "
            "no SSL, no Meta Pixel / Google Analytics, no contact form, or a weak Google Business Profile, "
            "while having enough review volume/price level to afford agency retainers."
        ),
    },
    "reputation_voice": {
        "id": "reputation_voice",
        "label": "Reputation & AI Voice / Booking",
        "short": "Missed calls, booking pain & 1–3★ review signals",
        "focus": (
            "Mine customer reviews and site UX for operational bottlenecks: missed phone calls, slow replies, "
            "no online scheduling/booking, long wait times, or unresponded 1-3 star complaints. "
            "Score high if they have strong customer demand/revenue signals plus clear booking/call-handling pain."
        ),
    },
    "b2b_outreach": {
        "id": "b2b_outreach",
        "label": "B2B Cold Outreach & Sales",
        "short": "Decision-maker extraction + personalized cold emails",
        "focus": (
            "Extract any Owner, Founder, Partner, or Manager name/title from the website text, summarize what "
            "they sell and who they serve, and craft highly specific, non-generic cold outreach grounded in real details "
            "from their site and Google listing."
        ),
    },
    "icp_budget": {
        "id": "icp_budget",
        "label": "ICP & Budget Qualifier",
        "short": "Verify affordability & fit for high-ticket offers",
        "focus": (
            "Strictly judge whether this business is independent (not a corporate mega-chain unless requested), "
            "matches the target ICP, and shows real revenue/budget capacity (review volume, price tier, multi-staff "
            "team, high-ticket services, active ad spend, established domain age) to afford the user's pricing."
        ),
    },
    "market_research": {
        "id": "market_research",
        "label": "Market & Competitor Research",
        "short": "District gaps, top leaders & pricing landscape",
        "focus": (
            "Analyze competitive positioning, category saturation, rating distribution, price positioning, "
            "and differentiators mentioned on their website and customer reviews."
        ),
    },
    "custom": {
        "id": "custom",
        "label": "Custom Offer / Rules",
        "short": "Your custom offer, price & evaluation criteria",
        "focus": "Evaluate the lead strictly according to the user's custom offer, pricing, and qualification rules.",
    },
}

STARTER_MISSIONS = [
    {
        "id": "starter_web_seo",
        "title": "High-Ticket Web & SEO Clients",
        "mode": "web_seo",
        "prompt": "Find 15 independent local businesses with high review volume (real revenue) whose website is missing SSL, analytics/pixel, or an online booking form. Remove chains and closed places from the table, rank the best ones, tell me why, and write personalized outreach emails.",
    },
    {
        "id": "starter_voice_reputation",
        "title": "Clinics Missing Calls / Weak Booking",
        "mode": "reputation_voice",
        "prompt": "Find local medical or dental clinics with strong demand where reviews complain about missed calls, scheduling delays, or slow follow-up, or whose website lacks live booking/chat. Clean poor fits from the table, rate each on affordability & need, and draft call + email pitches.",
    },
    {
        "id": "starter_b2b_outreach",
        "title": "Owner-Led Contractors w/ Emails",
        "mode": "b2b_outreach",
        "prompt": "Find established local contractors/home-service businesses with reachable emails and websites, extract any owner or manager names, clean out chains and directories, and generate tailored 2-sentence cold email icebreakers for each.",
    },
]


def list_modes() -> list[dict]:
    return [
        {"id": k, "label": v["label"], "short": v["short"]}
        for k, v in BUILTIN_MODES.items()
    ]


def build_lead_eval_prompt(lead: dict, mode_id: str = "web_seo",
                           offer: dict | None = None, custom_instruction: str = "") -> tuple[str, str]:
    mode = BUILTIN_MODES.get(mode_id, BUILTIN_MODES["web_seo"])
    offer_block = ""
    if offer:
        svc = offer.get("service_type") or offer.get("service") or ""
        budget = offer.get("min_budget") or offer.get("price") or ""
        niche = offer.get("target_niche") or offer.get("icp_rules") or ""
        notes = offer.get("pitch_notes") or offer.get("tone") or "concise, consultative, friendly"
        offer_block = (
            f"\nUSER OFFER PROFILE:\n"
            f"- Offer Name: {offer.get('name', '')}\n"
            f"- Service / Value: {svc}\n"
            f"- Price / Target Budget: {budget}\n"
            f"- Target Niche / ICP Rules: {niche}\n"
            f"- Pitch Notes / Tone: {notes}\n"
        )
    extra = f"\nADDITIONAL USER INSTRUCTIONS:\n{custom_instruction}\n" if custom_instruction else ""

    system_prompt = (
        "You are an elite B2B lead researcher & qualification analyst inside GME (Google Map Extractor). "
        "Evaluate ONLY using facts present in the supplied business record, website tech, cleaned website text, "
        "and Google Maps reviews. Never invent facts, names, or fake quotes.\n\n"
        f"ACTIVE MODE: {mode['label']}\n{mode['focus']}\n"
        f"{offer_block}{extra}\n"
        "Return valid JSON with this exact schema:\n"
        "{\n"
        '  "ai_score": <int 0-100 overall fit>,\n'
        '  "ai_affordability": "High" | "Medium" | "Low",\n'
        '  "ai_need": "High" | "Medium" | "Low",\n'
        '  "ai_verdict": "Strong Fit" | "Good Fit" | "Weak Fit" | "Skip",\n'
        '  "ai_owner": "<owner/founder/manager name & role if found in site text, else empty string>",\n'
        '  "ai_why": ["<short evidence-backed bullet 1>", "<bullet 2>", "<bullet 3>"],\n'
        '  "ai_pain_points": ["<concrete site/review pain point 1>", ...],\n'
        '  "ai_opportunity": "<1-line core pitch angle>",\n'
        '  "ai_subject": "<short natural cold email subject>",\n'
        '  "ai_icebreaker": "<2-sentence personalized opener citing real detail>",\n'
        '  "ai_call_script": "<2-3 sentence conversational cold call opener>",\n'
        '  "ai_followup": "<short 2-sentence follow-up message>"\n'
        "}"
    )

    # Trim payload cleanly to preserve tokens while keeping rich context
    reviews = lead.get("reviews")
    if isinstance(reviews, str):
        try:
            reviews = json.loads(reviews)
        except Exception:
            reviews = []
    compact_reviews = [
        {"rating": r.get("rating"), "time": r.get("time"), "text": (r.get("text") or "")[:240], "owner_replied": r.get("has_owner_reply")}
        for r in (reviews or [])[:12]
    ]

    lead_payload = {
        "name": lead.get("name"),
        "category": lead.get("category"),
        "address": lead.get("full_address"),
        "country": lead.get("country"),
        "rating": lead.get("rating"),
        "reviews_count": lead.get("reviews_count"),
        "price_level": lead.get("price_level") or lead.get("price_desc"),
        "is_ad": bool(lead.get("is_ad")),
        "closed_status": lead.get("closed_status"),
        "website": lead.get("website"),
        "phone": lead.get("phone"),
        "email": lead.get("email"),
        "emails": lead.get("emails"),
        "socials": lead.get("socials"),
        "hours_present": bool(lead.get("hours")),
        "web_tech": lead.get("web_tech"),
        "deterministic_lead_score": lead.get("lead_score"),
        "deterministic_reasons": lead.get("lead_reasons"),
        "website_text_excerpt": (lead.get("site_text") or "")[:3500],
        "reviews_sample": compact_reviews,
    }
    return system_prompt, json.dumps(lead_payload, ensure_ascii=False)


def build_market_brief_prompt(job: dict, facets: dict, top_leads: list[dict], mode_id: str = "market_research") -> tuple[str, str]:
    system_prompt = (
        "You are a senior local market analyst. Summarize the scraped Google Maps dataset into an actionable "
        "executive market brief grounded strictly in the provided numbers and sample leads. "
        "Return valid JSON:\n"
        "{\n"
        '  "headline": "<1 sentence market takeaway>",\n'
        '  "saturation_level": "Low" | "Moderate" | "High",\n'
        '  "digital_maturity": "<assessment of websites, SSL, pixels, emails>",\n'
        '  "top_opportunities": ["<opportunity 1>", "<opportunity 2>", "<opportunity 3>"],\n'
        '  "recommended_pitch": "<best offer angle for this market>"\n'
        "}"
    )
    payload = {
        "query": job.get("query"),
        "location": job.get("location"),
        "country": job.get("country") or job.get("gl"),
        "counts": (facets or {}).get("counts"),
        "top_areas": (facets or {}).get("areas", [])[:15],
        "sample_leads": [
            {
                "name": r.get("name"),
                "category": r.get("category"),
                "rating": r.get("rating"),
                "reviews_count": r.get("reviews_count"),
                "has_website": bool(r.get("website")),
                "has_email": bool(r.get("email")),
                "lead_score": r.get("lead_score"),
                "ai_score": r.get("ai_score"),
            }
            for r in top_leads[:15]
        ],
    }
    return system_prompt, json.dumps(payload, ensure_ascii=False)
