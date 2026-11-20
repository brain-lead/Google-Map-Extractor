"""Job orchestration: search -> enrich each lead via details -> persist."""
import asyncio
import json
import logging
import random
import re
import time
import uuid
from pathlib import Path

from backend import db
from backend.scraper import cookies as cookie_store
from backend.scraper import proxies as proxy_store
from backend.scraper.client import StaleSessionError
from backend.scraper.search import search as do_search
from backend.scraper.details import fetch_details
from backend.scraper.reviews import fetch_reviews
from backend.scraper.enrich import enrich_website
from backend.scraper.geocode import (reverse_geocode, geocode_locality,
                                    reset_rate_limited, was_rate_limited, was_blocked)
from backend.scraper import geo_locale
from backend.scraper import leadscore
from backend.scraper.area_scan import grid_centers, build_area_queries, grid_in_polygon
from backend.ws import manager
from backend.config import (DETAILS_CONCURRENCY, REQUEST_JITTER, WEB_CONCURRENCY,
                            BACKEND_DIR, DEFAULT_THREADS, DATA_DIR)

# Dedicated, append-only log of every job run (search/enrich milestones,
# per-lead outcomes, timings, warnings) so runs can be audited and tuned.
logger = logging.getLogger("job_runs")
if not logger.handlers:
    _h = logging.FileHandler(DATA_DIR / "job_runs.log")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# Enrichment pacing: lighter than the search jitter (website crawl runs in a
# thread so it must not block the event loop / other workers).
ENRICH_JITTER = (0.2, 0.6)

cancel_flags: dict[str, bool] = {}


def _settings_threads():
    """Fallback concurrency from the saved settings.json so a user's Settings
    'Concurrent threads' value is honored even if a job payload omits it
    (e.g. an older frontend bundle, or a re-run from History)."""
    try:
        import json
        p = DATA_DIR / "settings.json"
        if p.exists():
            s = json.loads(p.read_text())
            t = int(s.get("threads", 0))
            if 1 <= t <= 16:
                return t
    except Exception:
        pass
    return None


def new_job_id() -> str:
    return "job-" + uuid.uuid4().hex[:12]


def _parse_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _area_center(params: dict):
    poly = params.get("polygon")
    if poly and len(poly) >= 3:
        return (
            sum(p[0] for p in poly) / len(poly),
            sum(p[1] for p in poly) / len(poly),
        )
    la = _parse_float(params.get("lat"))
    ln = _parse_float(params.get("lng"))
    if la is not None and ln is not None:
        return (la, ln)
    return None


async def create_and_run(params: dict) -> str:
    # Resolve the active scoring config once and pass it through the whole run so
    # every result is scored with the user's chosen preset / custom weights.
    scoring_config = leadscore.resolve_config(params.pop("scoring", None))
    job_id = new_job_id()
    job = {
        "id": job_id,
        "query": params["query"],
        "location": params.get("location", ""),
        "gl": params.get("gl", "us"),
        "hl": params.get("hl", "en"),
        "max_results": params.get("max_results", 100),
        "proxy": params.get("proxy", ""),
        "area_scan": 1 if params.get("area_scan") else 0,
        "status": "pending",
        "error": "",
        "total": 0,
        "scraped": 0,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "polygon": json.dumps(params["polygon"]) if params.get("polygon") else None,
        "area_points": params.get("area_points"),
        "lat": _parse_float(params.get("lat")),
        "lng": _parse_float(params.get("lng")),
        "radius_km": _parse_float(params.get("radius_km")),
        "scan_meta": json.dumps({}),
    }
    # Resolve the search market (gl/hl) intelligently so a non-technical user
    # never has to set it by hand: area scans get their market from the drawn
    # area (computed in run_job), location searches use an explicit country if
    # provided, else try to detect the country from the typed location, else
    # fall back to the user's default market.
    # Location searches use the country the user picked from the dropdown
    # (params.country). Area scans resolve their country from the drawn area
    # (see run_job, which reverse-geocodes the polygon center). No free-text
    # guessing required.
    explicit_country = params.get("country") or ""
    if explicit_country:
        job["country"] = geo_locale.normalize_country(explicit_country)
        job["gl"] = geo_locale.gl_for_country(explicit_country) or job["gl"]
        job["hl"] = geo_locale.hl_for_country(explicit_country) or job["hl"]
    else:
        job["country"] = None
    db.insert_job(job)
    cancel_flags[job_id] = False
    asyncio.create_task(run_job(job_id, params, job, scoring_config))
    return job_id


async def run_job(job_id: str, params: dict, job: dict, scoring_config: dict = None):
    _job_start = time.time()
    # Concurrent Google calls (tile searches + details enrichment). Configurable
    # via the "threads" setting (default 2); each call rotates a proxy.
    try:
        threads = max(1, min(16, int(params.get("threads") or _settings_threads() or DEFAULT_THREADS)))
    except (TypeError, ValueError):
        threads = DEFAULT_THREADS
    async def build_queries():
        # Multi-keyword AND multi-location: every keyword is searched for every
        # location (e.g. "plumber" x ["Brooklyn New York", "Downtown Chicago"]) -> one
        # query each, each yielding up to max_results businesses.
        raw_q = params.get("query", "")
        keywords = [k.strip() for k in re.split(r"[,\n]+", raw_q) if k.strip()]
        if not keywords:
            keywords = [raw_q.strip()] if raw_q.strip() else [""]
        raw_loc = params.get("location", "")
        locations = [l.strip() for l in re.split(r"[,\n]+", raw_loc) if l.strip()]
        qs = []
        if params.get("area_scan"):
            poly = params.get("polygon")
            area_points = int(params.get("area_points") or 400)
            center = _area_center(params)
            if poly and len(poly) >= 3:
                centers = grid_in_polygon(poly, max_points=area_points)
            elif center is not None:
                rad = _parse_float(params.get("radius_km")) or 5.0
                centers = grid_centers(center[0], center[1], rad, max_points=area_points)
            else:
                centers = []
            if centers and center is not None:
                # Surface tile progress immediately so the user sees activity
                # instead of a static "Preparing scan…" while tiles are built.
                await manager.send(job_id, {"type": "notice",
                                            "message": f"Preparing {len(centers)} tile searches…"})
                await manager.send(job_id, {"type": "search", "query": "(tiles)",
                                            "found": 0, "queries_done": 0,
                                            "queries_total": len(centers)})
                # Area center -> city/country; used to target EVERY tile to
                # the right region (even tiles whose district lookup fails), so
                # we never fall back to the ignored `near <lat>,<lng>` form.
                clat, clng = center
                locality = await geocode_locality(clat, clng)
                logger.info("[%s] area-scan locality: %r", job_id, locality)
                # Per-tile district geocoding is a best-effort nicety that makes
                # tiles target distinct neighbourhoods. It must NEVER block the
                # first result: Nominatim is frequently rate-limited (HTTP 429),
                # and an unbounded gather here previously hung the whole job for
                # ~11 minutes before Google was ever queried. Cap it with a short
                # global deadline and fall back to coordinates if it is slow.
                # Per-tile district geocoding makes each tile target a distinct
                # neighbourhood (deeper coverage). Stay OSM-compliant (1 req/s)
                # and surface live telemetry (tiles resolved vs fallback, rate
                # limit / block status) so the UI can show exactly what happened.
                reset_rate_limited()
                total_tiles = len(centers)

                async def _send_tiles(geocoded):
                    await manager.send(job_id, {
                        "type": "tiles",
                        "total": total_tiles,
                        "geocoded": geocoded,
                        "fallback": total_tiles - geocoded,
                        "rate_limited": was_rate_limited(),
                        "blocked": was_blocked(),
                        "phase": "geocoding",
                    })

                labels = []
                geocoded = 0
                await _send_tiles(0)
                try:
                    async def _geo_seq():
                        nonlocal geocoded
                        for (la, ln) in centers:
                            # If Nominatim hard-blocks this IP, stop geocoding the
                            # rest immediately — they would all fail the same way.
                            if was_blocked():
                                labels.append(None)
                                continue
                            lab = await reverse_geocode(la, ln)
                            labels.append(lab)
                            if lab:
                                geocoded += 1
                            done = len(labels)
                            if done % 10 == 0 or done == total_tiles:
                                await _send_tiles(geocoded)
                    await asyncio.wait_for(_geo_seq(), timeout=300)
                except asyncio.TimeoutError:
                    logger.warning("[%s] area-scan geocoding hit budget (300s); "
                                   "continuing with coordinate-based tiles", job_id)
                await _send_tiles(geocoded)
                labelled = geocoded
                logger.info("[%s] area-scan: %d/%d tiles geocoded to a district; "
                            "all tiles targeted via locality %r", job_id, labelled,
                            len(centers), locality)
                if was_blocked():
                    await manager.send(job_id, {"type": "warning",
                        "message": f"Tile geocoding is BLOCKED (HTTP 403) for this IP: "
                                   f"0/{len(centers)} tiles got a district name, so every "
                                   f"tile falls back to coordinates and coverage is reduced. "
                                   f"The reverse geocoder (BigDataCloud) is rejecting "
                                   f"requests from this server's IP."})
                elif was_rate_limited():
                    await manager.send(job_id, {"type": "warning",
                        "message": f"Tile geocoding was rate-limited (HTTP 429): only "
                                   f"{labelled}/{len(centers)} tiles got a district name, "
                                   f"so the rest fell back to coordinates and coverage is "
                                   f"reduced."})
                else:
                    await manager.send(job_id, {"type": "notice",
                        "message": f"Area scan: {labelled}/{len(centers)} tiles got "
                                   f"district names; the rest use coordinates."})
                await manager.send(job_id, {
                    "type": "tiles", "total": len(centers), "geocoded": labelled,
                    "fallback": len(centers) - labelled,
                    "rate_limited": was_rate_limited(),
                    "blocked": was_blocked(), "phase": "searching",
                })
                # Persist the scan telemetry so History can show a per-job summary
                # (tiles used, what geocoded vs fell back, what failed) later.
                db.update_job(job_id, scan_meta=json.dumps({
                    "tiles_total": len(centers),
                    "geocoded": labelled,
                    "fallback": len(centers) - labelled,
                    "rate_limited": was_rate_limited(),
                    "blocked": was_blocked(),
                    "market": job.get("country") or job.get("gl"),
                }))
                for kw in keywords:
                    qs.extend(build_area_queries(kw, centers, labels, locality))
                logger.info("[%s] area-scan: %d unique search queries after "
                            "district de-duplication", job_id, len(qs))
        if not qs:
            for kw in keywords:
                for loc in (locations or [""]):
                    base = kw
                    if loc:
                        base = f"{kw} in {loc}"
                    qs.append(base)
        return qs

    fallback_proxy = proxy_store.normalize(params.get("proxy") or "")

    def pick_proxy():
        # Rotate through working proxies in the Proxies pool; fall back to default_proxy if set.
        return proxy_store.get_proxy() or fallback_proxy

    cookies = cookie_store.load_cookies() or {}
    _refresh_lock = asyncio.Lock()
    _last_refresh_ts = 0.0
    saw_block = False

    async def ensure_fresh_session(force: bool = False):
        nonlocal cookies, _last_refresh_ts
        async with _refresh_lock:
            now = time.time()
            if force:
                if (now - _last_refresh_ts) < 15.0:
                    return
            elif cookies and not cookie_store.is_session_stale():
                return
            _last_refresh_ts = now
            res = await cookie_store.refresh_cookies(proxy=pick_proxy())
            fresh = cookie_store.load_cookies()
            if fresh:
                cookies = fresh
            if res.get("generated") or res.get("imported"):
                logger.info("[%s] session auto-refreshed (valid=%s)", job_id, res.get("valid"))

    await ensure_fresh_session(force=False)

    # For area scans, target the search to the area's country market so
    # Google returns local results instead of the session's default (US).
    if params.get("area_scan"):
        _center = _area_center(params)
        if _center is not None:
            _loc = await geocode_locality(*_center)
            if _loc:
                # Smart market: resolve gl/hl straight from the area's country
                # (e.g. a city in another country -> its own gl), so area scans never default to
                # the US session market. Works for every country, not a fixed list.
                job["gl"] = geo_locale.gl_for_country(_loc) or job["gl"]
                job["hl"] = geo_locale.hl_for_country(_loc) or job["hl"]
                job["country"] = geo_locale.normalize_country(_loc)
                # Persist the resolved market so History / re-scan show the correct
                # country (the scan_meta update below only writes scan_meta).
                db.update_job(job_id, gl=job["gl"], hl=job["hl"], country=job["country"])
                logger.info("[%s] area-scan market set to gl=%s hl=%s (locality %r)",
                            job_id, job["gl"], job["hl"], _loc)

    gl, hl = job["gl"], job["hl"]

    async def search_with_retry(q, tries=4, record_failures=None):
        nonlocal saw_block
        last_err = None
        for attempt in range(tries):
            if cancel_flags.get(job_id):
                return [], []
            proxy = None if (attempt == tries - 1 and last_err is not None) else pick_proxy()
            try:
                res = await do_search(q, gl=gl, hl=hl,
                                      cookies=cookies, proxies=proxy,
                                      max_results=max_results)
                proxy_store.report_proxy(proxy, True)
                return res
            except StaleSessionError as e:
                proxy_store.report_proxy(proxy, False)
                saw_block = True
                last_err = e
                logger.warning("[%s] session block on %r (attempt %d/%d): %s — auto-refreshing",
                               job_id, q, attempt + 1, tries, e)
                await ensure_fresh_session(force=True)
                await asyncio.sleep((2 ** attempt) + random.uniform(0.5, 1.6))
            except Exception as e:
                proxy_store.report_proxy(proxy, False)
                last_err = e
                await asyncio.sleep(min(2 * (attempt + 1), 8) + random.uniform(0.2, 0.8))
        if record_failures is not None and not cancel_flags.get(job_id):
            record_failures.append((q, str(last_err)))
        else:
            await manager.send(job_id, {"type": "warning",
                                        "message": f"Skipped after {tries} retries: {q} — {last_err}"})
        return [], []

    max_results = params.get("max_results", 100)

    logger.info("[%s] START query=%r area_scan=%s area_points=%s gl=%s hl=%s "
                "max_results=%s threads=%s", job_id, params.get("query"),
                params.get("area_scan"), params.get("area_points"), gl, hl,
                max_results, threads)
    await manager.send(job_id, {"type": "start", "job_id": job_id})

    queries = await build_queries()
    logger.info("[%s] built %d search queries", job_id, len(queries))
    await manager.send(job_id, {"type": "notice",
                                "message": f"Prepared {len(queries)} tile searches."})
    leads = []
    refreshed = False
    try:
        for attempt in range(2):
            leads = []
            failed_queries = []
            sem = asyncio.Semaphore(threads)
            done = 0
            lock = asyncio.Lock()

            async def _search_one(qi, q):
                nonlocal done
                if cancel_flags.get(job_id):
                    return
                async with sem:
                    if cancel_flags.get(job_id):
                        return
                    try:
                        organic, ads = await search_with_retry(q, tries=4, record_failures=failed_queries)
                    except Exception as e:
                        await manager.send(job_id, {"type": "warning",
                                                    "message": f"Search failed for {q}: {e}"})
                        organic, ads = [], []
                    n = len(organic) + len(ads)
                    async with lock:
                        leads.extend(organic + ads)
                        done += 1
                        sent = done
                    logger.info("[%s] search[%d/%d] %r -> %d hits",
                                job_id, sent, len(queries), q, n)
                    await manager.send(job_id, {"type": "search", "query": q,
                                                "found": n,
                                                "queries_done": sent,
                                                "queries_total": len(queries)})
                    await asyncio.sleep(random.uniform(*REQUEST_JITTER))

            await asyncio.gather(*[_search_one(qi, q) for qi, q in enumerate(queries)])

            # Second-pass low-concurrency recovery sweep for any queries that failed
            if failed_queries and not cancel_flags.get(job_id):
                logger.info("[%s] running recovery pass for %d failed queries", job_id, len(failed_queries))
                await manager.send(job_id, {"type": "notice",
                                            "message": f"Retrying {len(failed_queries)} failed searches at lower speed…"})
                await ensure_fresh_session(force=True)
                await asyncio.sleep(2.5)
                rec_sem = asyncio.Semaphore(min(2, threads))

                async def _retry_failed(q_text, _prev_err):
                    if cancel_flags.get(job_id):
                        return
                    async with rec_sem:
                        if cancel_flags.get(job_id):
                            return
                        organic, ads = await search_with_retry(q_text, tries=3, record_failures=None)
                        if organic or ads:
                            async with lock:
                                leads.extend(organic + ads)

                await asyncio.gather(*[_retry_failed(qt, pe) for qt, pe in failed_queries])

            if leads or attempt == 1 or refreshed:
                break
            # Zero leads -> session may have expired. Auto-refresh once and retry.
            res = await cookie_store.refresh_cookies(proxy=pick_proxy())
            if not (res.get("generated") or res.get("imported")):
                break
            refreshed = True
            cookies = cookie_store.load_cookies() or cookies
        if not leads:
            err_msg = (
                "Google temporarily rate-limited or blocked requests from this IP. "
                "Add working proxies in the Proxies tab or reduce thread concurrency and retry."
                if saw_block
                else "No businesses matched this search. Try broadening your keyword or location."
            )
            await _fail(job_id, err_msg)
            cancel_flags.pop(job_id, None)
            return
    except Exception as e:
        await _fail(job_id, f"search failed: {e}")
        cookie_store.mark_stale(f"search failed: {e}")
        cancel_flags.pop(job_id, None)
        return

    # Dedupe leads by cid (keep first)
    seen = set()
    unique = []
    for l in leads:
        if l["cid"] in seen:
            continue
        seen.add(l["cid"])
        unique.append(l)

    total = len(unique)
    logger.info("[%s] search done: %d unique leads; starting enrichment "
                "(concurrency=%d)", job_id, total, threads)
    db.update_job(job_id, status="running", total=total)
    await manager.send(job_id, {"type": "enrich", "total": total})
    await manager.send(job_id, {"type": "notice",
                                "message": f"Enriching {total} businesses "
                                           f"(concurrency {threads})."})

    sem = asyncio.Semaphore(threads)
    web_sem = asyncio.Semaphore(WEB_CONCURRENCY)
    scraped = 0

    async def fetch_details_retry(cid, tries=4):
        last = None
        for i in range(tries):
            if cancel_flags.get(job_id):
                return None
            proxy = None if (i == tries - 1 and last is not None) else pick_proxy()
            try:
                res = await fetch_details(cid, gl=gl, hl=hl,
                                          cookies=cookies, proxies=proxy)
                proxy_store.report_proxy(proxy, True)
                return res
            except StaleSessionError as e:
                proxy_store.report_proxy(proxy, False)
                last = e
                logger.warning("[%s] session block on details %s (%d/%d) — auto-refreshing",
                               job_id, cid, i + 1, tries)
                await ensure_fresh_session(force=True)
                await asyncio.sleep((2 ** i) + random.uniform(0.4, 1.4))
            except Exception as e:  # transient network blip (curl 56, etc.)
                proxy_store.report_proxy(proxy, False)
                last = e
                logger.warning("[%s] details retry %d/%d for %s: %s",
                               job_id, i + 1, tries, cid, e)
                await asyncio.sleep(min(1.5 * (i + 1), 6) + random.uniform(0.2, 0.7))
        logger.warning("[%s] details skipped for %s after %d tries: %s",
                       job_id, cid, tries, last)
        await manager.send(job_id, {"type": "warning",
                                    "message": f"Details skipped for {cid}: {last}"})
        return None

    async def enrich(lead):
        nonlocal scraped
        biz = _lead_to_business(lead)
        t0 = time.time()
        try:
            # Google-limited step: place details + reviews. Keep concurrency low
            # (DETAILS_CONCURRENCY) to stay under Google's rate limit, and release
            # the slot before the website crawl so crawling isn't gated by it.
            async with sem:
                if cancel_flags.get(job_id):
                    return
                det = await fetch_details_retry(lead["cid"])
                if det is not None:
                    if det.website:
                        biz.website = det.website
                    if det.phone and not biz.phone:
                        biz.phone = det.phone
                    if biz.rating is None and det.rating is not None:
                        biz.rating = det.rating
                    if (det.reviews_count or 0) > (biz.reviews_count or 0):
                        biz.reviews_count = det.reviews_count
                    if det.email and not biz.email:
                        biz.email = det.email
                    if det.thumbnail and not biz.thumbnail:
                        biz.thumbnail = det.thumbnail
                    for f in ("price_level", "price_desc", "hours", "popular_times",
                              "menu_url", "closed_status", "amenities",
                              "service_options", "highlights", "popular_for"):
                        v = getattr(det, f, None)
                        if v:
                            setattr(biz, f, v)
                    if det.place_id:
                        try:
                            revs = await fetch_reviews(det.place_id, gl=gl, hl=hl,
                                                      cookies=cookies, proxies=pick_proxy())
                            if revs:
                                biz.reviews = json.dumps(revs, ensure_ascii=False)
                        except Exception as e:
                            logger.warning("[%s] reviews failed %s: %s",
                                           job_id, biz.name, e)
            # Third-party step: crawl the business's OWN website for emails/socials.
            # Different domain from Google -> no Google rate limit, so run it in a
            # large thread pool (web_sem) for high parallel throughput.
            site = biz.website
            if site and not cancel_flags.get(job_id):
                if not site.startswith("http"):
                    site = "https://" + site
                for web_try in range(2):
                    try:
                        async with web_sem:
                            enr = await asyncio.to_thread(
                                enrich_website, site,
                                include_domain_age=bool(scoring_config and scoring_config.get("use_domain_age")),
                            )
                        if enr["emails"]:
                            existing = set(json.loads(biz.emails)) if biz.emails else set()
                            existing.update(enr["emails"])
                            biz.emails = json.dumps(sorted(existing))
                            if not biz.email and enr["emails"]:
                                biz.email = enr["emails"][0]
                        if enr["socials"]:
                            biz.socials = json.dumps(enr["socials"])
                        if enr.get("web"):
                            biz.web_tech = json.dumps(enr["web"])
                        if enr.get("site_text"):
                            biz.site_text = enr["site_text"]
                        break
                    except Exception as e:
                        if web_try == 0:
                            await asyncio.sleep(1.0)
                            continue
                        logger.warning("[%s] website crawl failed %s: %s",
                                       job_id, biz.name, e)
        except Exception as e:
            logger.error("[%s] enrich error %s: %s", job_id, biz.name, e)
            await manager.send(job_id, {"type": "warning",
                                        "message": f"Enrich error {biz.name}: {e}"})
        # Compute an explainable lead score from the data we already collected,
        # using the active scoring config (preset / custom weights).
        try:
            sr = leadscore.score_business(biz, scoring_config)
            biz.lead_score = sr.score
            biz.lead_grade = sr.grade
            biz.lead_reasons = json.dumps(sr.reasons, ensure_ascii=False)
            biz.lead_tags = json.dumps(sr.tags)
        except Exception as e:
            logger.warning("[%s] leadscore failed %s: %s", job_id, biz.name, e)
        # Persist the base lead no matter what happened above.
        try:
            row = biz.to_row()
            db.insert_result(job_id, row)
            scraped += 1
            db.update_job(job_id, scraped=scraped)
            await manager.send(job_id, {
                "type": "progress", "scraped": scraped, "total": total,
                "name": biz.name, "cid": biz.cid,
            })
            logger.info("[%s] saved %d/%d %r (%.1fs)", job_id, scraped, total,
                        biz.name, time.time() - t0)
        except Exception as e:
            logger.error("[%s] save failed %s: %s", job_id, biz.name, e)
        await asyncio.sleep(random.uniform(*ENRICH_JITTER))

    results = await asyncio.gather(*[enrich(l) for l in unique],
                                   return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.error("[%s] enrich task raised: %s", job_id, r)
            await manager.send(job_id, {"type": "warning",
                                        "message": f"Enrich task error: {r}"})

    cancelled = bool(cancel_flags.pop(job_id, False))
    if cancelled:
        db.update_job(job_id, status="cancelled", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        await manager.send(job_id, {"type": "done", "status": "cancelled",
                                    "total": total, "scraped": scraped})
    else:
        db.update_job(job_id, status="completed", finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        await manager.send(job_id, {"type": "done", "status": "completed",
                                    "total": total, "scraped": scraped})
    logger.info("[%s] FINISHED status=%s total=%d scraped=%d duration=%.1fs",
                job_id, "cancelled" if cancelled else "completed",
                total, scraped, time.time() - _job_start)


def _lead_to_business(lead) -> "Business":  # type: ignore
    from backend.scraper.fields import Business
    return Business(
        cid=lead.get("cid", ""),
        name=lead.get("name", ""),
        category=lead.get("category", ""),
        street=lead.get("street", ""),
        city_state_zip=lead.get("city_state_zip", "") or lead.get("address", ""),
        full_address=lead.get("full_address", "") or lead.get("address", ""),
        rating=lead.get("rating"),
        reviews_count=lead.get("reviews_count"),
        website=lead.get("website") or "",
        phone=lead.get("phone") or "",
        email=lead.get("email", ""),
        latitude=lead.get("latitude"),
        longitude=lead.get("longitude"),
        place_id=lead.get("place_id") or "",
        gid=lead.get("gid", ""),
        timezone=lead.get("timezone") or "",
        is_ad=bool(lead.get("is_ad", False)),
    )


async def cancel_job(job_id: str):
    cancel_flags[job_id] = True
    db.update_job(job_id, status="cancelling")


async def _fail(job_id: str, msg: str):
    db.update_job(job_id, status="failed", error=msg,
                  finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    await manager.send(job_id, {"type": "error", "message": msg})
