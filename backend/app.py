"""FastAPI application: REST + WebSocket + serves the React frontend."""
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Query
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlparse

from backend import db
from backend import jobs
from backend.scraper import cookies as cookie_store
from backend.scraper import proxies as proxy_store
from backend.scraper.area_scan import grid_in_polygon
from backend.ws import manager
from backend.config import FRONTEND_DIST, DATA_DIR
from backend.licensing import core as licensing
from backend.scraper import leadscore
from backend.ai import config_store as ai_config_store
from backend.ai import modes as ai_modes
from backend.ai import providers as ai_providers
from backend.ai import agent as ai_agent
from backend import export as exporter

app = FastAPI(title="GME — Google Map Extractor", version="3.0.0")
db.init_db()
db.recover_stale_jobs()
db.backfill_countries()
# Seed default cookies from the bundled BurpSuite capture on first run.
# Set GMAP_DISABLE_CAPTURE_SEED=1 to skip (e.g. to test fully anonymous requests).
if not os.getenv("GMAP_DISABLE_CAPTURE_SEED"):
    cookie_store.ensure_default_cookies()

SETTINGS_FILE = DATA_DIR / "settings.json"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            pass
    return {"default_proxy": "", "gl": "us", "hl": "en", "threads": 2}


def save_settings(s: dict):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---------- Brain Lead licensing ----------
@app.get("/api/auth/status")
async def auth_status():
    """Current authorization status (cached)."""
    return licensing.check_authorization()


@app.get("/api/auth/branding")
async def auth_branding():
    """Branding + Telegram links for the UI."""
    return licensing.branding()


@app.post("/api/auth/activate")
async def auth_activate(payload: dict):
    """Activate a license key against the shared license backend."""
    return licensing.activate(payload.get("key", ""))


@app.post("/api/auth/reset-binding")
async def auth_reset_binding(payload: dict | None = None):
    """Self-service hardware binding reset and activation on this machine."""
    key = (payload or {}).get("key", "")
    return licensing.reset_binding(key)


@app.post("/api/auth/free-tier")
async def auth_free_tier():
    """Clear any saved conflicting license and switch to the free tier."""
    return licensing.use_free_tier()


@app.get("/api/auth/notifications")
async def auth_notifications():
    """Fetch active Brain Lead server announcements."""
    return licensing.check_notifications()


# ---------- Cookies ----------
@app.get("/api/cookies")
async def get_cookies():
    return cookie_store.cookie_status()


@app.post("/api/cookies")
async def post_cookies(payload: dict):
    text = payload.get("cookies", "")
    if not text.strip():
        return JSONResponse({"valid": False, "reason": "empty"}, status_code=400)
    return cookie_store.save_cookies(text)


@app.post("/api/cookies/test")
async def test_cookies(payload: dict):
    text = payload.get("cookies", "")
    if text.strip():
        cookies = cookie_store.parse_cookie_input(text)
    else:
        cookies = cookie_store.load_cookies()
    ok, reason = cookie_store.validate_cookies(cookies)
    return {"valid": ok, "reason": reason, "count": len(cookies)}


@app.post("/api/cookies/import-capture")
async def import_capture(payload: dict | None = None):
    """Re-import Google cookies from the bundled/provided capture file."""
    src = payload.get("source") if payload else None
    return cookie_store.import_from_capture(src)


@app.post("/api/cookies/auto-generate")
async def auto_generate():
    """Self-acquire fresh visitor cookies from Google (no login required)."""
    return await cookie_store.auto_generate_visitor_cookies()


@app.delete("/api/cookies")
async def clear_cookies():
    """Clear stored cookies and fall back to anonymous mode."""
    return cookie_store.clear_cookies()


# ---------- Proxies ----------
@app.get("/api/proxies")
async def get_proxies():
    return proxy_store.list_proxies()


@app.post("/api/proxies")
async def add_proxies(payload: dict):
    text = payload.get("proxies", "")
    return proxy_store.add_proxies(text)


@app.post("/api/proxies/upload")
async def upload_proxies(file: UploadFile = File(...)):
    text = (await file.read()).decode("utf-8", "ignore")
    return proxy_store.add_proxies(text)


@app.post("/api/proxies/test")
async def test_proxies():
    return await proxy_store.test_all()


@app.delete("/api/proxies")
async def delete_proxies():
    return proxy_store.clear_proxies()


# ---------- Settings ----------
@app.get("/api/settings")
async def get_settings():
    s = load_settings()
    s["has_google_creds"] = (DATA_DIR / "google_creds.json").exists()
    return s


@app.post("/api/settings")
async def post_settings(payload: dict):
    s = load_settings()
    s.update({k: payload[k] for k in ("default_proxy", "gl", "hl") if k in payload})
    if "threads" in payload:
        try:
            s["threads"] = max(1, min(16, int(payload["threads"])))
        except (TypeError, ValueError):
            pass
    if "max_results" in payload:
        try:
            s["max_results"] = max(10, min(1000, int(payload["max_results"])))
        except (TypeError, ValueError):
            pass
    if "scoring" in payload and isinstance(payload["scoring"], dict):
        sc = payload["scoring"]
        preset = sc.get("preset", "needs_help")
        if preset not in leadscore.PRESETS and preset != "custom":
            preset = "needs_help"
        clean = {"preset": preset}
        if sc.get("use_domain_age") is not None:
            clean["use_domain_age"] = bool(sc["use_domain_age"])
        if preset == "custom" and isinstance(sc.get("weights"), dict):
            clean["weights"] = {k: float(v) for k, v in sc["weights"].items() if k in leadscore.FACTORS}
        s["scoring"] = clean
    save_settings(s)
    return {**s, "has_google_creds": (DATA_DIR / "google_creds.json").exists()}


@app.get("/api/scoring")
async def scoring_meta():
    """Preset list, factor metadata, and the currently-stored config."""
    s = load_settings()
    return {
        "presets": {k: {"label": v["label"], "use_domain_age": v["use_domain_age"],
                        "weights": v["weights"]}
                    for k, v in leadscore.PRESETS.items()},
        "factors": [{"id": i, "label": l} for i, l in leadscore.FACTOR_META],
        "current": s.get("scoring", leadscore.DEFAULT_SCORING),
    }


@app.post("/api/jobs/{job_id}/rescore")
async def rescore_job_endpoint(job_id: str):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    cfg = leadscore.resolve_config(load_settings().get("scoring"))
    n = db.rescore_job(job_id, cfg)
    return {"ok": True, "updated": n}


@app.post("/api/rescore-all")
async def rescore_all_endpoint():
    cfg = leadscore.resolve_config(load_settings().get("scoring"))
    n = db.rescore_all(cfg)
    return {"ok": True, "updated": n}


# ---------- Jobs ----------
@app.get("/api/categories")
async def categories(q: str = None, limit: int = 25):
    """Distinct business categories for autocomplete (from captured results)."""
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 25
    return {"categories": db.distinct_categories(q, limit)}


@app.get("/api/countries")
async def list_countries():
    """All countries as {code, name, gl, hl} for the search-form dropdown,
    so the user can explicitly pick the market to search in."""
    from backend.scraper import geo_locale
    return {"countries": geo_locale.list_countries()}


@app.post("/api/jobs")
async def create_job(payload: dict):
    # Activation gate: only authorized users may start extractions.
    auth = licensing.check_authorization()
    if auth["status"] != "authorized":
        return JSONResponse(
            {"error": "activation_required", "message": auth["message"]},
            status_code=403,
        )
    s = load_settings()
    raw_threads = payload.get("threads") if payload.get("threads") not in (None, "") else s.get("threads", 2)
    try:
        threads = max(1, min(16, int(raw_threads or 2)))
    except (TypeError, ValueError):
        threads = 2
    limited = auth.get("limited")
    try:
        max_results = max(1, int(payload.get("max_results") or s.get("max_results") or 100))
    except (TypeError, ValueError):
        max_results = 100
    try:
        area_points = max(1, int(payload.get("area_points") or 400))
    except (TypeError, ValueError):
        area_points = 400
    if limited:
        # Free tier: cap results and restrict area-scan tile count.
        caps = licensing.free_limits()
        max_results = min(max_results, caps["max_results_per_search"])
        if payload.get("area_scan"):
            area_points = min(area_points, caps["area_scan_max_tiles"])
    raw_lat = payload.get("lat")
    raw_lng = payload.get("lng")
    params = {
        "query": payload.get("query", "").strip(),
        "location": payload.get("location", "").strip(),
        "country": payload.get("country", "") or "",
        "gl": payload.get("gl") or s.get("gl", "us"),
        "hl": payload.get("hl") or s.get("hl", "en"),
        "max_results": max_results,
        "proxy": payload.get("proxy") or s.get("default_proxy", ""),
        "area_scan": payload.get("area_scan", False),
        "polygon": payload.get("polygon") or None,
        "area_points": area_points,
        "lat": None if raw_lat in (None, "") else raw_lat,
        "lng": None if raw_lng in (None, "") else raw_lng,
        "radius_km": payload.get("radius_km") or 5,
        "threads": threads,
        # Active scoring config (preset / custom weights) so every result is
        # scored with the user's chosen system. create_and_run pops this.
        "scoring": leadscore.resolve_config(s.get("scoring")),
    }
    if not params["query"]:
        return JSONResponse({"error": "query required"}, status_code=400)
    job_id = await jobs.create_and_run(params)
    return {"job_id": job_id, "status": "pending"}


@app.post("/api/preview-tiles")
async def preview_tiles(payload: dict | None = None):
    """Compute the search-tile grid for a drawn polygon + cap, so the UI can
    preview (as map dots) exactly which points will be searched."""
    # Activation gate.
    auth = licensing.check_authorization()
    if auth["status"] != "authorized":
        return JSONResponse(
            {"error": "activation_required", "message": auth["message"]},
            status_code=403,
        )
    payload = payload or {}
    poly = payload.get("polygon") or []
    area_points = int(payload.get("area_points") or 400)
    if auth.get("limited"):
        # Free tier: restrict area-scan tile count.
        caps = licensing.free_limits()
        area_points = min(area_points, caps["area_scan_max_tiles"])
    if len(poly) < 3:
        return {"points": [], "count": 0}
    pts = grid_in_polygon(poly, max_points=area_points)
    return {"points": [list(p) for p in pts], "count": len(pts)}


@app.get("/api/jobs")
async def list_jobs_endpoint(limit: int = None, offset: int = 0):
    jobs = db.list_jobs(limit=limit, offset=offset)
    return {"jobs": jobs, "total": db.count_jobs()}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    db.delete_job(job_id)
    return {"status": "deleted"}


@app.get("/api/jobs/compare")
async def compare_jobs_endpoint(job: str = Query(...), baseline: str = None):
    """New-business tracker: diff `job` against a baseline run.

    If `baseline` is omitted, the most recent completed run with the same
    query+location is used (previous_job_for). Returns new / removed / changed
    (rating & review deltas) businesses.
    """
    cur = db.get_job(job)
    if not cur:
        return JSONResponse({"error": "not found"}, status_code=404)
    base = db.get_job(baseline) if baseline else db.previous_job_for(job)
    if not base:
        return {"baseline": None, "current": cur, "new": [], "removed": [], "changed": []}
    diff = db.compare_jobs(job, base["id"])
    return {"baseline": base, "current": cur, **diff}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    return job


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    await jobs.cancel_job(job_id)
    return {"status": "cancelling"}


@app.get("/api/jobs/{job_id}/results")
async def job_results(job_id: str, q: str = None, limit: int = 24, offset: int = 0,
                      min_rating: float = None, min_reviews: int = Query(None),
                      min_ai_score: int = Query(None), affordability: str = None,
                      ai_verdict: str = None, removed_only: bool = False,
                      location: list[str] = Query(None),
                      country: list[str] = Query(None),
                      has_email: bool = False, has_social: bool = False, has_website: bool = False,
                      has_phone: bool = False, has_hours: bool = False, has_menu: bool = False,
                      has_reviews: bool = False, hot_only: bool = False, sort: str = "default"):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    filters = {
        "min_rating": min_rating, "min_reviews": min_reviews,
        "min_ai_score": min_ai_score, "affordability": affordability,
        "ai_verdict": ai_verdict, "removed_only": removed_only,
        "location": location or [], "country": country or [],
        "has_email": has_email, "has_social": has_social, "has_website": has_website,
        "has_phone": has_phone, "has_hours": has_hours, "has_menu": has_menu,
        "has_reviews": has_reviews, "hot_only": hot_only, "sort": sort,
    }
    return db.get_results(job_id, limit=limit, offset=offset, q=q, filters=filters)


@app.get("/api/jobs/{job_id}/facets")
async def job_facets(job_id: str):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return db.get_facets(job_id)


@app.get("/api/jobs/{job_id}/report")
async def job_report(job_id: str):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    facets = db.get_facets(job_id)
    top = db.get_results(job_id, limit=10, filters={"sort": "lead_desc"})["items"]
    return {"job": db.get_job(job_id), "facets": facets, "top_leads": top}


# ---------- Thumbnail proxy ----------
# Google's /a/... profile-photo CDN URLs are hotlink-protected and fail when a
# browser loads them cross-origin from localhost. We proxy them through our own
# origin (fetched server-side with a Google Referer) so they always render.
_THUMB_ALLOWED_SUFFIXES = (
    "googleusercontent.com", "ggpht.com", "googleapis.com",
)


# In-memory thumbnail cache so re-filtering / re-rendering doesn't re-fetch
# the same image from Google's CDN. Bounded to avoid unbounded growth.
_THUMB_CACHE: dict = {}


@app.get("/api/thumb")
async def thumb_proxy(u: str = ""):
    if not u:
        return JSONResponse({"error": "missing url"}, status_code=400)
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return JSONResponse({"error": "bad url"}, status_code=400)
    host = p.netloc.lower()
    if not any(host == s or host.endswith("." + s) for s in _THUMB_ALLOWED_SUFFIXES):
        return JSONResponse({"error": "disallowed host"}, status_code=400)
    cached = _THUMB_CACHE.get(u)
    if cached:
        data, ctype = cached
        return StreamingResponse(iter([data]), media_type=ctype or "image/jpeg",
                                  headers={"Cache-Control": "public, max-age=1800"})
    from backend.scraper.client import fetch_image
    data, ctype = fetch_image(u)
    if not data:
        return JSONResponse({"error": "fetch failed"}, status_code=502)
    if len(_THUMB_CACHE) > 3000:
        _THUMB_CACHE.clear()
    _THUMB_CACHE[u] = (data, ctype)
    return StreamingResponse(iter([data]), media_type=ctype or "image/jpeg",
                              headers={"Cache-Control": "public, max-age=1800"})


# ---------- Export ----------
@app.get("/api/jobs/{job_id}/export")
async def export_job(job_id: str, format: str = "csv", q: str = None,
                      min_rating: float = None, min_reviews: int = Query(None),
                      min_ai_score: int = Query(None), affordability: str = None,
                      ai_verdict: str = None,
                      location: list[str] = Query(None),
                      country: list[str] = Query(None),
                      has_email: bool = False, has_social: bool = False, has_website: bool = False,
                      has_phone: bool = False, has_hours: bool = False, has_menu: bool = False,
                      has_reviews: bool = False, hot_only: bool = False, sort: str = "default",
                      crm: str = None):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    filters = {
        "min_rating": min_rating, "min_reviews": min_reviews,
        "min_ai_score": min_ai_score, "affordability": affordability,
        "ai_verdict": ai_verdict,
        "location": location or [], "country": country or [],
        "has_email": has_email, "has_social": has_social, "has_website": has_website,
        "has_phone": has_phone, "has_hours": has_hours, "has_menu": has_menu,
        "has_reviews": has_reviews, "hot_only": hot_only, "sort": sort,
    }
    if format == "csv":
        data = jobs_export_csv(job_id, q, filters)
        return StreamingResponse(iter([data]), media_type="text/csv",
                                  headers={"Content-Disposition": f"attachment; filename={job_id}.csv"})
    if format == "json":
        data = jobs_export_json(job_id, q, filters)
        return StreamingResponse(iter([data]), media_type="application/json",
                                  headers={"Content-Disposition": f"attachment; filename={job_id}.json"})
    if format == "xlsx":
        data = jobs_export_xlsx(job_id, q, filters)
        return StreamingResponse(iter([data]),
                                  media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  headers={"Content-Disposition": f"attachment; filename={job_id}.xlsx"})
    if format == "sheets":
        creds = (DATA_DIR / "google_creds.json")
        if not creds.exists():
            return JSONResponse({"error": "upload google_creds.json first"}, status_code=400)
        url = jobs_export_sheets(job_id, str(creds), q, filters)
        return {"url": url}
    if format == "crm":
        crm = (crm or "hubspot").lower()
        if crm not in ("hubspot", "salesforce", "zoho"):
            return JSONResponse({"error": "unknown crm (use hubspot|salesforce|zoho)"}, status_code=400)
        data = jobs_export_crm(job_id, crm, q, filters)
        return StreamingResponse(iter([data]), media_type="text/csv",
                                  headers={"Content-Disposition": f'attachment; filename={job_id}_{crm}.csv'})
    return JSONResponse({"error": "unknown format"}, status_code=400)


def jobs_export_csv(job_id, q, filters=None):
    from backend.export import to_csv
    return to_csv(job_id, q, filters)


def jobs_export_json(job_id, q, filters=None):
    from backend.export import to_json
    return to_json(job_id, q, filters)


def jobs_export_xlsx(job_id, q, filters=None):
    from backend.export import to_xlsx
    return to_xlsx(job_id, q, filters)


def jobs_export_sheets(job_id, creds, q, filters=None):
    from backend.export import to_google_sheets
    return to_google_sheets(job_id, creds, q=q, filters=filters)


def jobs_export_crm(job_id, crm, q, filters=None):
    from backend.export import to_crm_csv
    return to_crm_csv(job_id, crm, q, filters)


@app.post("/api/settings/google_creds")
async def upload_creds(file: UploadFile = File(...)):
    data = await file.read()
    try:
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict):
            return JSONResponse({"error": "Invalid JSON service account file"}, status_code=400)
    except Exception:
        return JSONResponse({"error": "File is not valid UTF-8 JSON"}, status_code=400)
    (DATA_DIR / "google_creds.json").write_bytes(data)
    return {"ok": True, "has_google_creds": True}


# ---------- AI Config, Models, Offers, Missions, Inline Commands & Shortlists ----------
def _ai_config_payload(pub: dict) -> dict:
    prov = pub.get("provider") or "gemini"
    sel = ai_providers.resolve_model(prov, pub.get("tier") or "fast", pub.get("custom_model") or "")
    return {
        **pub,
        "selected_model": sel,
        "provider_models": ai_providers.PROVIDER_MODELS,
        "curated_models": {p: ai_providers.get_curated_models(p) for p in ai_config_store.PROVIDERS},
        "modes": ai_modes.list_modes(),
        "starter_missions": ai_modes.STARTER_MISSIONS,
    }


@app.get("/api/ai/config")
async def get_ai_config():
    return _ai_config_payload(ai_config_store.public_config())


@app.put("/api/ai/config")
async def put_ai_config(payload: dict):
    saved = ai_config_store.save_config(payload or {})
    return _ai_config_payload(saved)


@app.get("/api/ai/models")
async def list_ai_models_get(provider: str = None, refresh: bool = False):
    return await ai_providers.fetch_available_models(
        provider=provider or None,
        force_refresh=bool(refresh),
    )


@app.post("/api/ai/models")
async def list_ai_models_post(payload: dict | None = None):
    p = payload or {}
    raw_key = p.get("api_key")
    api_key = None
    if raw_key and "•" not in str(raw_key):
        api_key = str(raw_key).strip()
    return await ai_providers.fetch_available_models(
        provider=p.get("provider") or None,
        api_key=api_key,
        base_url=p.get("base_url") if p.get("base_url") not in (None, "") else None,
        force_refresh=bool(p.get("refresh")),
    )


@app.post("/api/ai/test")
async def test_ai_connection(payload: dict | None = None):
    p = payload or {}
    raw_key = p.get("api_key")
    api_key = None
    if raw_key and "•" not in str(raw_key):
        api_key = str(raw_key).strip()
    try:
        res = await ai_providers.test_connection(
            provider=p.get("provider") or None,
            tier=p.get("tier") or None,
            model=p.get("custom_model") or p.get("model") or None,
            api_key=api_key,
            base_url=p.get("base_url") if p.get("base_url") not in (None, "") else None,
        )
        return res
    except ai_providers.AIProviderError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/api/ai/modes")
async def get_ai_modes():
    return {"modes": ai_modes.list_modes(), "starter_missions": ai_modes.STARTER_MISSIONS}


@app.get("/api/ai/offers")
async def get_ai_offers():
    return {"offers": db.list_offers()}


@app.post("/api/ai/offers")
async def save_ai_offer(payload: dict):
    offer = db.save_offer(payload or {})
    return {"offer": offer}


@app.delete("/api/ai/offers/{offer_id}")
async def delete_ai_offer(offer_id: str):
    ok = db.delete_offer(offer_id)
    if not ok:
        return JSONResponse({"error": "Offer not found"}, status_code=404)
    return {"status": "deleted"}


@app.get("/api/ai/missions")
async def list_ai_missions(limit: int = 40):
    return {"missions": db.list_missions(limit=limit)}


@app.post("/api/ai/missions")
async def create_ai_mission(payload: dict):
    p = payload or {}
    goal = (p.get("goal") or p.get("message") or "").strip()
    if not goal:
        return JSONResponse({"error": "goal is required"}, status_code=400)
    try:
        mission = await ai_agent.start_mission(
            goal=goal,
            mode_id=p.get("mode_id") or "custom",
            offer_id=p.get("offer_id") or "",
            job_id=p.get("job_id") or "",
            title=p.get("title") or "",
            model=p.get("model") or "",
        )
        return {"mission": mission}
    except ai_providers.AIProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/ai/missions/{mission_id}")
async def get_ai_mission(mission_id: str):
    m = db.get_mission(mission_id)
    if not m:
        return JSONResponse({"error": "Mission not found"}, status_code=404)
    return {"mission": m, "messages": db.list_mission_messages(mission_id)}


@app.get("/api/ai/missions/{mission_id}/log")
async def get_ai_mission_log(mission_id: str, limit: int = 250):
    m = db.get_mission(mission_id)
    if not m:
        return JSONResponse({"error": "Mission not found"}, status_code=404)
    msgs = db.list_mission_messages(mission_id, limit=500)
    tool_calls = [msg for msg in msgs if msg.get("role") == "tool"]
    return {
        "mission": m,
        "tool_calls": tool_calls,
        "log_file": str(DATA_DIR / "ai_runs.log"),
        "log_lines": ai_agent.read_ai_log_tail(mission_id=mission_id, limit=limit),
    }


@app.get("/api/ai/logs")
async def get_ai_logs(mission_id: str = "", limit: int = 250):
    return {
        "log_file": str(DATA_DIR / "ai_runs.log"),
        "lines": ai_agent.read_ai_log_tail(mission_id=mission_id, limit=limit),
    }


@app.post("/api/ai/missions/{mission_id}/message")
async def send_ai_mission_message(mission_id: str, payload: dict):
    p = payload or {}
    msg = (p.get("message") or p.get("goal") or "").strip()
    if not msg:
        return JSONResponse({"error": "message is required"}, status_code=400)
    try:
        m = await ai_agent.send_mission_message(
            mission_id,
            msg,
            mode_id=p.get("mode_id"),
            offer_id=p.get("offer_id"),
            job_id=p.get("job_id"),
            model=p.get("model"),
        )
        return {"mission": m}
    except ai_providers.AIProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=409)


@app.post("/api/ai/missions/{mission_id}/cancel")
async def cancel_ai_mission(mission_id: str):
    return await ai_agent.cancel_mission(mission_id)


@app.delete("/api/ai/missions/{mission_id}")
async def delete_ai_mission(mission_id: str):
    await ai_agent.cancel_mission(mission_id)
    ok = db.delete_mission(mission_id)
    if not ok:
        return JSONResponse({"error": "Mission not found"}, status_code=404)
    return {"status": "deleted"}


@app.websocket("/api/ai/missions/{mission_id}/ws")
async def ws_ai_mission(ws: WebSocket, mission_id: str):
    await ws.accept()
    try:
        await ai_agent.mission_ws.stream(mission_id, ws)
    except WebSocketDisconnect:
        pass


@app.post("/api/jobs/{job_id}/ai-analyze")
async def job_ai_analyze(job_id: str, payload: dict | None = None):
    p = payload or {}
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        return await ai_agent.analyze_job_leads(
            job_id,
            mode_id=p.get("mode_id") or "web_seo",
            offer_id=p.get("offer_id") or "",
            custom_instruction=p.get("custom_instruction") or "",
            cids=p.get("cids"),
            limit=int(p.get("limit") or 25),
            model=p.get("model") or None,
        )
    except ai_providers.AIProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/jobs/{job_id}/ai-command")
async def job_ai_command(job_id: str, payload: dict):
    p = payload or {}
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        return await ai_agent.parse_and_run_command(
            job_id,
            command_text=p.get("command") or "",
            mode_id=p.get("mode_id") or "custom",
            offer_id=p.get("offer_id") or "",
            model=p.get("model") or None,
        )
    except ai_providers.AIProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/jobs/{job_id}/ai-market-brief")
async def job_ai_market_brief(job_id: str, payload: dict | None = None):
    p = payload or {}
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        return await ai_agent.generate_job_market_brief(job_id, mode_id=p.get("mode_id") or "market_research")
    except ai_providers.AIProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/jobs/{job_id}/remove-leads")
async def job_remove_leads(job_id: str, payload: dict):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    p = payload or {}
    n = db.remove_leads(job_id, p.get("cids") or [], reason=p.get("reason") or "Removed by user")
    return {"removed": n, "removed_count": db.get_facets(job_id)["counts"].get("removed_count", 0)}


@app.post("/api/jobs/{job_id}/restore-removed")
async def job_restore_removed(job_id: str, payload: dict | None = None):
    if not db.get_job(job_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    p = payload or {}
    n = db.restore_leads(job_id, cids=p.get("cids"))
    return {"restored": n, "removed_count": db.get_facets(job_id)["counts"].get("removed_count", 0)}


@app.get("/api/lists")
async def get_saved_lists():
    return {"lists": db.list_saved_lists()}


@app.post("/api/lists")
async def create_saved_list(payload: dict):
    p = payload or {}
    sl = db.create_list(name=p.get("name") or "Shortlist", description=p.get("description") or "")
    return {"list": sl}


@app.get("/api/lists/{list_id}")
async def get_saved_list_detail(list_id: str):
    sl = db.get_saved_list(list_id)
    if not sl:
        return JSONResponse({"error": "Shortlist not found"}, status_code=404)
    return {"list": sl}


@app.delete("/api/lists/{list_id}")
async def delete_saved_list(list_id: str):
    ok = db.delete_list(list_id)
    if not ok:
        return JSONResponse({"error": "Shortlist not found"}, status_code=404)
    return {"status": "deleted"}


@app.post("/api/lists/{list_id}/items")
async def add_saved_list_items(list_id: str, payload: dict):
    if not db.get_saved_list(list_id):
        return JSONResponse({"error": "Shortlist not found"}, status_code=404)
    p = payload or {}
    leads = list(p.get("leads") or [])
    job_id = p.get("job_id") or ""
    cids = p.get("cids") or []
    if job_id and cids:
        for c in cids:
            row = db.get_result_by_cid(job_id, c)
            if row:
                leads.append(row)
    added = db.add_list_items(list_id, leads, notes=p.get("notes") or "")
    return {"added": added, "list": db.get_saved_list(list_id)}


@app.patch("/api/lists/{list_id}/items/{item_id}")
async def patch_saved_list_item(list_id: str, item_id: int, payload: dict):
    p = payload or {}
    item = db.update_list_item(item_id, status=p.get("status"), notes=p.get("notes"))
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    return {"item": item}


@app.delete("/api/lists/{list_id}/items/{item_id}")
async def delete_saved_list_item(list_id: str, item_id: int):
    ok = db.delete_list_item(item_id)
    if not ok:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    return {"status": "deleted"}


@app.get("/api/lists/{list_id}/export")
async def export_saved_list(list_id: str, format: str = "csv", crm: str | None = None):
    sl = db.get_saved_list(list_id)
    if not sl:
        return JSONResponse({"error": "Shortlist not found"}, status_code=404)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in sl["name"])[:40] or list_id
    fmt = (format or "csv").lower()
    if crm or fmt == "crm":
        c = (crm or "hubspot").lower()
        data = exporter.export_shortlist(list_id, fmt="csv", crm=c)
        return StreamingResponse(iter([data]), media_type="text/csv",
                                  headers={"Content-Disposition": f"attachment; filename={safe_name}_{c}.csv"})
    if fmt == "json":
        data = exporter.export_shortlist(list_id, fmt="json")
        return StreamingResponse(iter([data]), media_type="application/json",
                                  headers={"Content-Disposition": f"attachment; filename={safe_name}.json"})
    if fmt == "xlsx":
        data = exporter.export_shortlist(list_id, fmt="xlsx")
        return StreamingResponse(iter([data]),
                                  media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  headers={"Content-Disposition": f"attachment; filename={safe_name}.xlsx"})
    data = exporter.export_shortlist(list_id, fmt="csv")
    return StreamingResponse(iter([data]), media_type="text/csv",
                              headers={"Content-Disposition": f"attachment; filename={safe_name}.csv"})


# ---------- WebSocket progress ----------
@app.websocket("/api/jobs/{job_id}/ws")
async def ws_progress(ws: WebSocket, job_id: str):
    await ws.accept()
    try:
        await manager.stream(job_id, ws)
    except WebSocketDisconnect:
        pass


# ---------- Frontend ----------
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
else:
    @app.get("/")
    async def index_fallback():
        return JSONResponse({
            "status": "backend ok",
            "note": "frontend not built; run `npm run build` in frontend/.",
            "endpoints": ["/api/jobs", "/api/cookies", "/api/health"],
        })
