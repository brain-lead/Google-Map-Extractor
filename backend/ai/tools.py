"""Internal GME tool definitions and async execution dispatcher for the AI Autopilot."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from curl_cffi import AsyncSession

from backend import db, jobs as job_runner, export as exporter
from backend.ai import config_store
from backend.config import IMPERSONATE
from backend.licensing import core as licensing
from backend.scraper import cookies as cookie_store
from backend.scraper import enrich, leadscore, proxies as proxy_store, reviews as review_scraper
from backend.ws import manager as job_ws_manager


def _load_app_settings() -> dict:
    from backend.config import DATA_DIR
    p = DATA_DIR / "settings.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"default_proxy": "", "gl": "us", "hl": "en", "threads": 2}


@dataclass
class MissionContext:
    mission_id: str
    active_job_id: str = ""
    mode_id: str = "custom"
    offer: dict | None = None
    guardrails: dict = field(default_factory=lambda: dict(config_store.DEFAULT_GUARDRAILS))
    searches_used: int = 0
    deep_cids: set[str] = field(default_factory=set)
    last_view: dict | None = None
    is_cancelled: Callable[[], bool] = lambda: False
    emit: Callable[[dict], Awaitable[None]] | None = None

    async def notify(self, payload: dict) -> None:
        if self.emit:
            await self.emit(payload)


# Canonical tool schemas understood cleanly by Gemini, Claude, OpenAI, and Ollama.
TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "geocode_place",
        "description": "Convert a city, neighborhood, district, or address string into latitude/longitude coordinates and country for area scanning.",
        "parameters": {
            "type": "object",
            "properties": {
                "place_name": {"type": "string", "description": "City, neighborhood, or address (e.g. 'Austin, Texas', 'Shoreditch, London')."},
            },
            "required": ["place_name"],
        },
    },
    {
        "name": "start_keyword_search",
        "description": "Launch a Google Maps search job for one or MULTIPLE comma-separated business niches in ONE combined Results table! When finding the best local businesses for an offer across a city, include 4-6 relevant niches comma-separated (e.g. 'private hospital, boutique hotel, car dealership, fitness gym, salon spa, real estate agency') so all niches can be compared & ranked side-by-side.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Single niche OR comma-separated multi-niche keywords (e.g. 'private clinic, fitness gym, luxury hotel, car dealership, restaurant')."},
                "location": {"type": "string", "description": "City, neighborhood, or area (e.g. 'Abuja', 'Austin, TX')."},
                "country": {"type": "string", "description": "Optional country name (e.g. 'Nigeria', 'United States', 'United Kingdom')."},
                "max_results": {"type": "integer", "description": "Maximum results per niche keyword (default 25-40)."},
            },
            "required": ["query", "location"],
        },
    },
    {
        "name": "start_area_scan",
        "description": "Launch a dense multi-tile geographic area scan around coordinates or a place name to capture deep local coverage.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Business keyword (e.g. 'med spa', 'auto repair')."},
                "location": {"type": "string", "description": "Human-readable area name; auto-geocoded if lat/lng omitted."},
                "lat": {"type": "number", "description": "Center latitude (optional if location provided)."},
                "lng": {"type": "number", "description": "Center longitude (optional if location provided)."},
                "radius_km": {"type": "number", "description": "Scan radius in km (default 5)."},
                "area_points": {"type": "integer", "description": "Grid tile count (default 12)."},
                "max_results": {"type": "integer", "description": "Max results per tile (default 40)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "wait_for_job",
        "description": "Wait for a running extraction job to finish while streaming live progress to the user. Always call this after starting a search before querying results.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID returned by start_keyword_search or start_area_scan."},
                "timeout_sec": {"type": "integer", "description": "Max seconds to wait (default 180)."},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "cancel_job",
        "description": "Cancel a currently running extraction job.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID to cancel."},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "list_jobs",
        "description": "List recent extraction jobs so you can inspect existing scraped datasets without scraping again.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many recent jobs to list (default 15)."},
            },
        },
    },
    {
        "name": "compare_jobs",
        "description": "Compare a job against a previous baseline run (or auto-detect previous run) to find new businesses, removed businesses, and rating/review changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Current job ID."},
                "baseline_job_id": {"type": "string", "description": "Optional older baseline job ID."},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "query_results",
        "description": "Search, filter, sort, and read leads inside a job (defaults to active_job_id if omitted). Soft-removed leads are excluded unless removed_only=true.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID (optional if active job already set)."},
                "q": {"type": "string", "description": "Text search across name, address, category, website, email, AI notes."},
                "min_rating": {"type": "number", "description": "Minimum star rating."},
                "min_reviews": {"type": "integer", "description": "Minimum review count."},
                "min_ai_score": {"type": "integer", "description": "Minimum AI fit score (0-100)."},
                "affordability": {"type": "string", "description": "Filter by AI affordability: High, Medium, or Low."},
                "has_email": {"type": "boolean", "description": "Only leads with an email address."},
                "has_website": {"type": "boolean", "description": "Only leads with a website."},
                "has_phone": {"type": "boolean", "description": "Only leads with a phone number."},
                "sort": {"type": "string", "description": "Sort order: default, ai_desc, lead_desc, rating_desc, reviews_desc, rating_asc."},
                "limit": {"type": "integer", "description": "Page size (default 35, max 100)."},
                "offset": {"type": "integer", "description": "Pagination offset (default 0)."},
            },
        },
    },
    {
        "name": "read_reviews",
        "description": "Read stored Google Maps customer reviews (and owner replies) for a business, or fetch them on demand if missing.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID (optional if active job set)."},
                "cid": {"type": "string", "description": "Business CID."},
                "limit": {"type": "integer", "description": "Max reviews to return (default 20)."},
            },
            "required": ["cid"],
        },
    },
    {
        "name": "inspect_website",
        "description": "Read cleaned homepage/contact/about website text, tech stack (SSL, analytics, pixel, generator), emails, and social profiles for a business. Fetches website on demand if not yet cached.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID (optional if active job set)."},
                "cid": {"type": "string", "description": "Business CID."},
                "force_rescrape": {"type": "boolean", "description": "Re-fetch live website even if cached."},
            },
            "required": ["cid"],
        },
    },
    {
        "name": "apply_table_view",
        "description": "Update the live Results table in the UI (search query, filters, sort order, highlighted CIDs) so the user immediately sees the curated view.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID to focus in the UI."},
                "q": {"type": "string", "description": "Text search filter."},
                "sort": {"type": "string", "description": "Sort: ai_desc, lead_desc, rating_desc, reviews_desc, rating_asc, default."},
                "min_rating": {"type": "number", "description": "Min star rating."},
                "min_reviews": {"type": "integer", "description": "Min review count."},
                "min_ai_score": {"type": "integer", "description": "Min AI score."},
                "affordability": {"type": "string", "description": "High, Medium, Low, or empty."},
                "ai_verdict": {"type": "string", "description": "Filter by verdict e.g. 'Strong Fit'."},
                "has_email": {"type": "boolean", "description": "Only leads with email."},
                "has_website": {"type": "boolean", "description": "Only leads with website."},
                "hot_only": {"type": "boolean", "description": "Only Hot leads."},
                "highlight_cids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of top CIDs to highlight in the UI.",
                },
            },
        },
    },
    {
        "name": "remove_leads",
        "description": "Soft-remove unwanted leads (e.g. chains, wrong category, closed places, low fit) from the active table with 1-click Restore support.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID (optional if active job set)."},
                "cids": {"type": "array", "items": {"type": "string"}, "description": "List of business CIDs to remove."},
                "reason": {"type": "string", "description": "Short human-readable reason for removal."},
            },
            "required": ["cids"],
        },
    },
    {
        "name": "restore_leads",
        "description": "Undo soft-removal and restore removed leads back into the active table (restores specific CIDs, or all removed leads if cids omitted).",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID (optional if active job set)."},
                "cids": {"type": "array", "items": {"type": "string"}, "description": "Optional specific CIDs to restore; omit to restore all."},
            },
        },
    },
    {
        "name": "update_lead_intelligence",
        "description": "Save AI qualification score, affordability, need, owner name, verdict, bullet reasons, pain points, and tailored outreach scripts onto one or more leads so they display in the table, modal, and exports.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID (optional if active job set)."},
                "updates": {
                    "type": "array",
                    "description": "List of lead intelligence records.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cid": {"type": "string"},
                            "ai_score": {"type": "integer", "description": "0-100 overall fit score."},
                            "ai_affordability": {"type": "string", "description": "High | Medium | Low"},
                            "ai_need": {"type": "string", "description": "High | Medium | Low"},
                            "ai_verdict": {"type": "string", "description": "Strong Fit | Good Fit | Weak Fit | Skip"},
                            "ai_owner": {"type": "string", "description": "Extracted owner/decision-maker name & role if found."},
                            "ai_why": {"type": "string", "description": "Concise evidence-backed explanation of why this lead matches or misses."},
                            "ai_pain_points": {"type": "array", "items": {"type": "string"}},
                            "ai_campaign": {
                                "type": "object",
                                "description": "Personalized pitch snippets: email_subject, icebreaker, call_opener, followup.",
                                "properties": {
                                    "email_subject": {"type": "string"},
                                    "icebreaker": {"type": "string"},
                                    "call_opener": {"type": "string"},
                                    "followup": {"type": "string"},
                                },
                            },
                        },
                        "required": ["cid", "ai_score", "ai_verdict", "ai_why"],
                    },
                },
            },
            "required": ["updates"],
        },
    },
    {
        "name": "rescore_job",
        "description": "Recalculate deterministic GME lead scores using a preset ('balanced', 'marketing_agency', 'reputation', 'local_seo', 'b2b_sales').",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID."},
                "preset": {"type": "string", "description": "Preset name."},
            },
        },
    },
    {
        "name": "save_offer_profile",
        "description": "Save a reusable user Offer Profile (service, minimum budget/retainer, target niche, pitch notes) into settings.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Profile name e.g. 'Web Redesign $2k'."},
                "service_type": {"type": "string"},
                "min_budget": {"type": "string"},
                "target_niche": {"type": "string"},
                "pitch_notes": {"type": "string"},
                "mode_id": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_shortlists",
        "description": "List all saved cross-job lead shortlists.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "save_to_shortlist",
        "description": "Save top curated leads by CID into a named persistent Shortlist (creates the list if it does not exist yet).",
        "parameters": {
            "type": "object",
            "properties": {
                "list_name": {"type": "string", "description": "Shortlist name e.g. 'Austin Dental Hot Leads'."},
                "cids": {"type": "array", "items": {"type": "string"}, "description": "CIDs of leads to save."},
                "job_id": {"type": "string", "description": "Source job ID (optional if active job set)."},
                "description": {"type": "string", "description": "Optional shortlist description."},
                "notes": {"type": "string", "description": "Optional note attached to saved leads."},
            },
            "required": ["list_name", "cids"],
        },
    },
    {
        "name": "export_leads",
        "description": "Prepare a downloadable export link for a job or shortlist in csv, xlsx, json, or CRM format (hubspot, salesforce, zoho).",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID to export."},
                "list_id": {"type": "string", "description": "Or Shortlist ID to export."},
                "format": {"type": "string", "description": "csv, xlsx, json, or crm."},
                "crm": {"type": "string", "description": "hubspot, salesforce, or zoho when format=crm."},
                "min_ai_score": {"type": "integer", "description": "Optional minimum AI score filter on job export."},
            },
        },
    },
    {
        "name": "check_health",
        "description": "Check GME licensing tier/limits, cookie session status, proxy pool health, and AI settings.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def _resolve_job_id(args: dict, ctx: MissionContext) -> str:
    jid = (args.get("job_id") or ctx.active_job_id or "").strip()
    if not jid:
        raise ValueError("No job_id provided and no active dataset selected yet. Start a search or call list_jobs first.")
    return jid


async def _forward_geocode(place_name: str) -> dict:
    q = (place_name or "").strip()
    if not q:
        return {"error": "place_name is required"}
    async with AsyncSession(impersonate=IMPERSONATE, timeout=12) as s:
        # 1. OpenStreetMap Nominatim search
        try:
            r = await s.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "jsonv2", "q": q, "limit": 3, "addressdetails": 1},
                headers={"User-Agent": "google-map-extractor/3.0 (mailto:support@brainlead.dev)"},
            )
            if r.status_code == 200:
                arr = r.json()
                if isinstance(arr, list) and arr:
                    top = arr[0]
                    addr = top.get("address") or {}
                    return {
                        "query": q,
                        "lat": float(top["lat"]),
                        "lng": float(top["lon"]),
                        "display_name": top.get("display_name") or q,
                        "country": addr.get("country") or "",
                        "country_code": (addr.get("country_code") or "").lower(),
                        "suggested_radius_km": 5,
                    }
        except Exception:
            pass
        # 2. Open-Meteo keyless geocoding fallback
        try:
            r2 = await s.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": q, "count": 3, "language": "en", "format": "json"},
            )
            if r2.status_code == 200:
                res = (r2.json() or {}).get("results") or []
                if res:
                    top = res[0]
                    disp = ", ".join(p for p in [top.get("name"), top.get("admin1"), top.get("country")] if p)
                    return {
                        "query": q,
                        "lat": float(top["latitude"]),
                        "lng": float(top["longitude"]),
                        "display_name": disp or q,
                        "country": top.get("country") or "",
                        "country_code": (top.get("country_code") or "").lower(),
                        "suggested_radius_km": 5,
                    }
        except Exception:
            pass
    return {"error": f"Could not geocode '{q}'. Try specifying 'City, Country' directly in start_keyword_search."}


async def _build_and_start_job(payload: dict, ctx: MissionContext) -> dict:
    max_searches = int(ctx.guardrails.get("max_searches", 3))
    if ctx.searches_used >= max_searches:
        return {
            "error": f"Search guardrail reached ({max_searches} searches per turn/mission). "
                     "Analyze current results or ask the user before searching further."
        }
    auth = licensing.check_authorization()
    if auth.get("status") != "authorized":
        return {"error": f"Licensing blocked search: {auth.get('message', 'Activation required')}"}

    s = _load_app_settings()
    limited = bool(auth.get("limited"))
    max_scrapes_guard = int(ctx.guardrails.get("max_scrapes", 100))
    req_max = int(payload.get("max_results") or 40)
    max_results = max(1, min(req_max, max_scrapes_guard))
    area_points = max(1, int(payload.get("area_points") or 12))

    if limited:
        caps = licensing.free_limits()
        max_results = min(max_results, caps["max_results_per_search"])
        if payload.get("area_scan"):
            area_points = min(area_points, caps["area_scan_max_tiles"])

    params = {
        "query": (payload.get("query") or "").strip(),
        "location": (payload.get("location") or "").strip(),
        "country": (payload.get("country") or "").strip(),
        "gl": s.get("gl", "us"),
        "hl": s.get("hl", "en"),
        "max_results": max_results,
        "proxy": s.get("default_proxy", ""),
        "area_scan": bool(payload.get("area_scan")),
        "polygon": payload.get("polygon"),
        "area_points": area_points,
        "lat": payload.get("lat"),
        "lng": payload.get("lng"),
        "radius_km": float(payload.get("radius_km") or 5.0),
        "threads": max(1, min(8, int(s.get("threads", 2) or 2))),
        "scoring": leadscore.resolve_config(s.get("scoring")),
    }
    if not params["query"]:
        return {"error": "query is required"}

    job_id = await job_runner.create_and_run(params)
    ctx.searches_used += 1
    ctx.active_job_id = job_id
    db.update_mission(ctx.mission_id, job_id=job_id)
    await ctx.notify({"type": "job_started", "job_id": job_id, "query": params["query"], "location": params["location"]})
    return {
        "job_id": job_id,
        "status": "pending",
        "max_results": max_results,
        "area_scan": params["area_scan"],
        "free_tier_limited": limited,
    }


async def _wait_for_job(args: dict, ctx: MissionContext) -> dict:
    job_id = _resolve_job_id(args, ctx)
    timeout_sec = max(15, min(600, int(args.get("timeout_sec") or 180)))
    deadline = time.time() + timeout_sec
    last_sent_len = 0

    while True:
        if ctx.is_cancelled():
            await job_runner.cancel_job(job_id)
            return {"job_id": job_id, "status": "cancelled"}

        hist = list(job_ws_manager.history.get(job_id, ()))
        if len(hist) > last_sent_len:
            for msg in hist[last_sent_len:]:
                await ctx.notify({"type": "job_progress", "job_id": job_id, "event": msg})
            last_sent_len = len(hist)

        job = db.get_job(job_id)
        if not job:
            return {"error": f"Job '{job_id}' not found"}
        if job.get("status") in ("completed", "failed", "cancelled", "interrupted"):
            facets = db.get_facets(job_id)
            return {
                "job_id": job_id,
                "status": job.get("status"),
                "error": job.get("error") or "",
                "total": job.get("total", 0),
                "scraped": job.get("scraped", 0),
                "counts": facets.get("counts"),
            }
        if time.time() >= deadline:
            return {
                "job_id": job_id,
                "status": job.get("status"),
                "timed_out": True,
                "scraped": job.get("scraped", 0),
                "total": job.get("total", 0),
            }
        await asyncio.sleep(0.8)


def _compact_lead(r: dict) -> dict:
    reasons = r.get("lead_reasons")
    if isinstance(reasons, str):
        try:
            reasons = json.loads(reasons)
        except Exception:
            pass
    web_tech = r.get("web_tech")
    if isinstance(web_tech, str):
        try:
            web_tech = json.loads(web_tech)
        except Exception:
            pass
    return {
        "cid": r.get("cid"),
        "name": r.get("name"),
        "category": r.get("category"),
        "rating": r.get("rating"),
        "reviews_count": r.get("reviews_count"),
        "price_level": r.get("price_level"),
        "price_desc": r.get("price_desc"),
        "full_address": r.get("full_address"),
        "country": r.get("country"),
        "website": r.get("website"),
        "phone": r.get("phone"),
        "email": r.get("email"),
        "emails": r.get("emails"),
        "socials": r.get("socials"),
        "hours_present": bool(r.get("hours")),
        "closed_status": r.get("closed_status"),
        "web_tech": web_tech,
        "lead_score": r.get("lead_score"),
        "lead_grade": r.get("lead_grade"),
        "lead_reasons": reasons,
        "ai_score": r.get("ai_score"),
        "ai_affordability": r.get("ai_affordability"),
        "ai_need": r.get("ai_need"),
        "ai_owner": r.get("ai_owner"),
        "ai_verdict": r.get("ai_verdict"),
        "ai_why": r.get("ai_why"),
    }


async def execute_tool(name: str, args: dict | None, ctx: MissionContext) -> dict:
    """Execute one internal GME tool call safely and return JSON-serializable dict."""
    args = args or {}

    if name == "geocode_place":
        return await _forward_geocode(args.get("place_name", ""))

    if name == "start_keyword_search":
        return await _build_and_start_job(
            {
                "query": args.get("query", ""),
                "location": args.get("location", ""),
                "country": args.get("country", ""),
                "max_results": args.get("max_results", 40),
                "area_scan": False,
            },
            ctx,
        )

    if name == "start_area_scan":
        lat, lng = args.get("lat"), args.get("lng")
        loc = (args.get("location") or "").strip()
        if (lat is None or lng is None) and loc:
            geo = await _forward_geocode(loc)
            if "error" not in geo:
                lat, lng = geo["lat"], geo["lng"]
        if lat is None or lng is None:
            return {"error": "Area scan requires lat/lng or a geocodable location name."}
        return await _build_and_start_job(
            {
                "query": args.get("query", ""),
                "location": loc,
                "lat": lat,
                "lng": lng,
                "radius_km": args.get("radius_km", 5),
                "area_points": args.get("area_points", 12),
                "max_results": args.get("max_results", 40),
                "area_scan": True,
            },
            ctx,
        )

    if name == "wait_for_job":
        return await _wait_for_job(args, ctx)

    if name == "cancel_job":
        jid = _resolve_job_id(args, ctx)
        await job_runner.cancel_job(jid)
        return {"job_id": jid, "status": "cancelling"}

    if name == "list_jobs":
        limit = max(1, min(50, int(args.get("limit") or 15)))
        rows = db.list_jobs(limit=limit)
        return {
            "jobs": [
                {
                    "id": j["id"],
                    "query": j.get("query"),
                    "location": j.get("location"),
                    "country": j.get("country"),
                    "status": j.get("status"),
                    "scraped": j.get("scraped", 0),
                    "total": j.get("total", 0),
                    "created_at": j.get("created_at"),
                }
                for j in rows
            ]
        }

    if name == "compare_jobs":
        jid = _resolve_job_id(args, ctx)
        base_id = (args.get("baseline_job_id") or "").strip()
        if not base_id:
            prev = db.previous_job_for(jid)
            if not prev:
                return {"job_id": jid, "error": "No previous completed run with matching query + location found."}
            base_id = prev["id"]
        diff = db.compare_jobs(jid, base_id)
        return {
            "job_id": jid,
            "baseline_job_id": base_id,
            "new_count": len(diff["new"]),
            "removed_count": len(diff["removed"]),
            "changed_count": len(diff["changed"]),
            "new_sample": [_compact_lead(r) for r in diff["new"][:10]],
            "changed_sample": diff["changed"][:10],
        }

    if name == "query_results":
        jid = _resolve_job_id(args, ctx)
        limit = max(1, min(100, int(args.get("limit") or 35)))
        offset = max(0, int(args.get("offset") or 0))
        filters = {
            "min_rating": args.get("min_rating"),
            "min_reviews": args.get("min_reviews"),
            "min_ai_score": args.get("min_ai_score"),
            "affordability": args.get("affordability"),
            "has_email": bool(args.get("has_email")),
            "has_website": bool(args.get("has_website")),
            "has_phone": bool(args.get("has_phone")),
            "sort": args.get("sort") or "lead_desc",
        }
        res = db.get_results(jid, limit=limit, offset=offset, q=args.get("q") or None, filters=filters)
        facets = db.get_facets(jid)
        return {
            "job_id": jid,
            "total": res["total"],
            "removed_count": res.get("removed_count", 0),
            "offset": offset,
            "counts": facets.get("counts"),
            "items": [_compact_lead(r) for r in res["items"]],
        }

    if name == "read_reviews":
        jid = _resolve_job_id(args, ctx)
        cid = (args.get("cid") or "").strip()
        row = db.get_result_by_cid(jid, cid)
        if not row:
            return {"error": f"Business cid='{cid}' not found in job {jid}"}
        max_rev = max(1, min(30, int(args.get("limit") or 20)))
        revs = []
        raw_rev = row.get("reviews")
        if raw_rev:
            try:
                revs = json.loads(raw_rev) if isinstance(raw_rev, str) else list(raw_rev)
            except Exception:
                revs = []
        if not revs and row.get("place_id"):
            try:
                cookies = cookie_store.load_cookies()
                proxy = proxy_store.get_proxy()
                job = db.get_job(jid) or {}
                revs = await review_scraper.fetch_reviews(
                    row["place_id"],
                    gl=job.get("gl") or "us",
                    hl=job.get("hl") or "en",
                    cookies=cookies,
                    proxies=proxy,
                )
            except Exception:
                revs = []
        return {
            "job_id": jid,
            "cid": cid,
            "name": row.get("name"),
            "rating": row.get("rating"),
            "reviews_count": row.get("reviews_count"),
            "reviews": revs[:max_rev],
        }

    if name == "inspect_website":
        jid = _resolve_job_id(args, ctx)
        cid = (args.get("cid") or "").strip()
        row = db.get_result_by_cid(jid, cid)
        if not row:
            return {"error": f"Business cid='{cid}' not found in job {jid}"}
        max_deep = int(ctx.guardrails.get("max_deep_leads", 25))
        if cid not in ctx.deep_cids and len(ctx.deep_cids) >= max_deep:
            return {
                "error": f"Deep inspection guardrail reached ({max_deep} leads). Summarize current findings instead."
            }
        ctx.deep_cids.add(cid)

        site_text = (row.get("site_text") or "").strip()
        web_tech = row.get("web_tech") or ""
        emails = row.get("emails") or ""
        socials = row.get("socials") or ""
        website = (row.get("website") or "").strip()

        if website.startswith("http") and (not site_text or args.get("force_rescrape")):
            enr = await asyncio.to_thread(enrich.enrich_website, website)
            site_text = (enr.get("site_text") or "").strip()
            found_emails = enr.get("emails") or []
            found_socials = enr.get("socials") or []
            found_web = enr.get("web") or {}
            extra = {}
            if found_emails and not row.get("email"):
                extra["email"] = found_emails[0]
            if found_emails:
                emails = json.dumps(found_emails)
                extra["emails"] = emails
            if found_socials:
                socials = json.dumps(found_socials)
                extra["socials"] = socials
            if found_web:
                web_tech = json.dumps(found_web)
                extra["web_tech"] = web_tech
            db.update_result_site_text(jid, cid, site_text, extra=extra)

        return {
            "job_id": jid,
            "cid": cid,
            "name": row.get("name"),
            "website": website,
            "email": row.get("email") or "",
            "emails": emails,
            "socials": socials,
            "web_tech": web_tech,
            "site_text": site_text[:3600] if site_text else "(No website text extracted)",
        }

    if name == "apply_table_view":
        jid = _resolve_job_id(args, ctx)
        ctx.active_job_id = jid
        view = {
            "q": args.get("q") or "",
            "sort": args.get("sort") or "ai_desc",
            "min_rating": "" if args.get("min_rating") is None else str(args.get("min_rating")),
            "min_reviews": "" if args.get("min_reviews") is None else str(args.get("min_reviews")),
            "min_ai_score": "" if args.get("min_ai_score") is None else str(args.get("min_ai_score")),
            "affordability": args.get("affordability") or "",
            "ai_verdict": args.get("ai_verdict") or "",
            "has_email": bool(args.get("has_email")),
            "has_website": bool(args.get("has_website")),
            "hot_only": bool(args.get("hot_only")),
            "highlight_cids": list(args.get("highlight_cids") or []),
        }
        ctx.last_view = view
        await ctx.notify({"type": "ui_view", "job_id": jid, "view": view})
        return {"ok": True, "job_id": jid, "view": view}

    if name == "remove_leads":
        jid = _resolve_job_id(args, ctx)
        cids = list(args.get("cids") or [])
        reason = (args.get("reason") or "Removed by AI Copilot").strip()
        n = db.remove_leads(jid, cids, reason=reason)
        facets = db.get_facets(jid)
        await ctx.notify({
            "type": "ui_table_changed",
            "job_id": jid,
            "action": "removed",
            "count": n,
            "cids": cids,
            "removed_count": facets["counts"].get("removed_count", 0),
        })
        return {"job_id": jid, "removed": n, "total_removed_in_job": facets["counts"].get("removed_count", 0)}

    if name == "restore_leads":
        jid = _resolve_job_id(args, ctx)
        cids = args.get("cids")
        n = db.restore_leads(jid, cids=cids)
        facets = db.get_facets(jid)
        await ctx.notify({
            "type": "ui_table_changed",
            "job_id": jid,
            "action": "restored",
            "count": n,
            "removed_count": facets["counts"].get("removed_count", 0),
        })
        return {"job_id": jid, "restored": n, "total_removed_in_job": facets["counts"].get("removed_count", 0)}

    if name == "update_lead_intelligence":
        jid = _resolve_job_id(args, ctx)
        updates = args.get("updates") or []
        saved = 0
        for item in updates:
            cid = str(item.get("cid") or "").strip()
            if not cid:
                continue
            payload = {**item, "ai_mode": item.get("ai_mode") or ctx.mode_id}
            if db.update_lead_ai(jid, cid, payload):
                saved += 1
        await ctx.notify({"type": "ui_table_changed", "job_id": jid, "action": "ai_updated", "count": saved})
        return {"job_id": jid, "updated": saved}

    if name == "rescore_job":
        jid = _resolve_job_id(args, ctx)
        preset = (args.get("preset") or "balanced").strip()
        cfg = leadscore.resolve_config({"preset": preset})
        n = db.rescore_job(jid, config=cfg)
        await ctx.notify({"type": "ui_table_changed", "job_id": jid, "action": "rescored", "count": n})
        return {"job_id": jid, "preset": preset, "rescored": n}

    if name == "save_offer_profile":
        offer = db.save_offer({
            "name": args.get("name") or "Custom Offer",
            "service_type": args.get("service_type") or "",
            "min_budget": args.get("min_budget") or "",
            "target_niche": args.get("target_niche") or "",
            "pitch_notes": args.get("pitch_notes") or "",
            "mode_id": args.get("mode_id") or ctx.mode_id or "custom",
        })
        await ctx.notify({"type": "ui_offers_updated", "offer": offer})
        return {"saved": True, "offer": offer}

    if name == "list_shortlists":
        return {"lists": db.list_saved_lists()}

    if name == "save_to_shortlist":
        jid = _resolve_job_id(args, ctx)
        lname = (args.get("list_name") or "AI Shortlist").strip()
        cids = [str(c).strip() for c in (args.get("cids") or []) if str(c).strip()]
        existing = next(
            (l for l in db.list_saved_lists() if l["name"].strip().lower() == lname.lower()),
            None,
        )
        if existing:
            sl = existing
        else:
            sl = db.create_list(lname, description=args.get("description") or "")
        rows = [db.get_result_by_cid(jid, c) for c in cids]
        leads = [r for r in rows if r]
        added = db.add_list_items(sl["id"], leads, notes=args.get("notes") or "")
        await ctx.notify({"type": "ui_shortlist_updated", "list_id": sl["id"], "name": sl["name"], "added": added})
        return {"list_id": sl["id"], "name": sl["name"], "added": added}

    if name == "export_leads":
        fmt = (args.get("format") or "csv").lower()
        crm = (args.get("crm") or "").lower()
        list_id = (args.get("list_id") or "").strip()
        if list_id:
            sl = db.get_saved_list(list_id)
            if not sl:
                return {"error": f"Shortlist '{list_id}' not found"}
            qstr = f"format={fmt}" + (f"&crm={crm}" if crm else "")
            url = f"/api/lists/{list_id}/export?{qstr}"
            cnt = sl.get("item_count", 0)
        else:
            jid = _resolve_job_id(args, ctx)
            qparams = [f"format={'crm' if crm or fmt == 'crm' else fmt}"]
            if crm or fmt == "crm":
                qparams.append(f"crm={crm or 'hubspot'}")
            if args.get("min_ai_score") is not None:
                qparams.append(f"min_ai_score={int(args['min_ai_score'])}")
            url = f"/api/jobs/{jid}/export?" + "&".join(qparams)
            cnt = db.count_results(jid)
        info = {"download_url": url, "format": crm or fmt, "estimated_count": cnt}
        await ctx.notify({"type": "ui_export_ready", **info})
        return info

    if name == "check_health":
        auth = licensing.check_authorization()
        ai_cfg = config_store.public_config()
        ck = cookie_store.cookie_status()
        px = proxy_store.list_proxies()
        working_px = sum(1 for p in px if p.get("status") == "working")
        return {
            "licensing": {"status": auth.get("status"), "tier": auth.get("tier"), "limited": bool(auth.get("limited"))},
            "ai": {"provider": ai_cfg["provider"], "tier": ai_cfg["tier"], "configured": ai_cfg["configured"]},
            "cookies": {"count": ck.get("count", 0), "valid": bool(ck.get("valid"))},
            "proxies": {"total": len(px), "working": working_px},
        }

    return {"error": f"Unknown tool: {name}"}
