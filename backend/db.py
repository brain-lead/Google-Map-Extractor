"""SQLite persistence: jobs + scraped results.

Synchronous sqlite3 wrapper (called inside asyncio.to_thread from the app).
"""
import sqlite3
import json
import re
import time
import uuid
from pathlib import Path
from backend.config import DB_PATH

# US state/territory codes — used to normalise 'State ZIP' address tails to
# 'United States' when deriving the country facet.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    query       TEXT,
    location    TEXT,
    gl          TEXT,
    hl          TEXT,
    max_results INTEGER,
    proxy       TEXT,
    area_scan   INTEGER DEFAULT 0,
    status      TEXT,
    error       TEXT,
    total       INTEGER DEFAULT 0,
    scraped     INTEGER DEFAULT 0,
    created_at  TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT,
    cid           TEXT,
    name          TEXT,
    category      TEXT,
    street        TEXT,
    city_state_zip TEXT,
    full_address  TEXT,
    rating        REAL,
    reviews_count INTEGER,
    website       TEXT,
    phone         TEXT,
    email         TEXT,
    latitude      REAL,
    longitude     REAL,
    place_id      TEXT,
    gid           TEXT,
    timezone      TEXT,
    thumbnail     TEXT,
    is_ad         INTEGER DEFAULT 0,
    price_level   INTEGER,
    price_desc    TEXT,
    hours         TEXT,
    popular_times TEXT,
    menu_url      TEXT,
    closed_status TEXT,
    amenities     TEXT,
    service_options TEXT,
    highlights    TEXT,
    popular_for   TEXT,
    emails        TEXT,
    socials       TEXT,
    reviews       TEXT,
    lead_score    INTEGER DEFAULT 0,
    lead_grade    TEXT,
    lead_reasons  TEXT,
    lead_tags     TEXT,
    country       TEXT,
    web_tech      TEXT,
    site_text     TEXT,
    is_removed    INTEGER DEFAULT 0,
    removed_reason TEXT,
    ai_score      INTEGER,
    ai_affordability TEXT,
    ai_need       TEXT,
    ai_owner      TEXT,
    ai_verdict    TEXT,
    ai_why        TEXT,
    ai_pain_points TEXT,
    ai_campaign   TEXT,
    ai_mode       TEXT,
    ai_updated_at TEXT,
    raw_json      TEXT,
    created_at    TEXT,
    UNIQUE(job_id, cid)
);
CREATE INDEX IF NOT EXISTS idx_results_job ON results(job_id);
CREATE INDEX IF NOT EXISTS idx_results_removed ON results(job_id, is_removed);

CREATE TABLE IF NOT EXISTS ai_offers (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    service_type TEXT,
    min_budget   TEXT,
    target_niche TEXT,
    pitch_notes  TEXT,
    mode_id      TEXT DEFAULT 'custom',
    created_at   TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS ai_missions (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    goal         TEXT,
    mode_id      TEXT DEFAULT 'custom',
    offer_id     TEXT,
    job_id       TEXT,
    model        TEXT,
    status       TEXT DEFAULT 'pending',
    summary      TEXT,
    error        TEXT,
    created_at   TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS ai_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT,
    tool_name   TEXT,
    tool_args   TEXT,
    tool_result TEXT,
    job_id      TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_mission ON ai_messages(mission_id);

CREATE TABLE IF NOT EXISTS saved_lists (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS saved_list_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id          TEXT NOT NULL,
    job_id           TEXT,
    cid              TEXT,
    name             TEXT,
    category         TEXT,
    full_address     TEXT,
    phone            TEXT,
    email            TEXT,
    emails           TEXT,
    website          TEXT,
    rating           REAL,
    reviews_count    INTEGER,
    lead_score       INTEGER,
    ai_score         INTEGER,
    ai_affordability TEXT,
    ai_verdict       TEXT,
    ai_why           TEXT,
    ai_campaign      TEXT,
    notes            TEXT,
    status           TEXT DEFAULT 'New',
    snapshot_json    TEXT,
    added_at         TEXT,
    UNIQUE(list_id, cid)
);
CREATE INDEX IF NOT EXISTS idx_saved_items_list ON saved_list_items(list_id);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=30.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init_db() -> None:
    c = _conn()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    # Run column migrations for pre-existing tables BEFORE indexes that reference new columns
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(results)").fetchall()}
    except sqlite3.OperationalError:
        cols = set()
    if cols:
        new_cols = [
            ("price_level", "INTEGER"), ("price_desc", "TEXT"), ("hours", "TEXT"),
            ("popular_times", "TEXT"), ("menu_url", "TEXT"), ("closed_status", "TEXT"),
            ("amenities", "TEXT"), ("service_options", "TEXT"), ("highlights", "TEXT"),
            ("popular_for", "TEXT"), ("emails", "TEXT"), ("socials", "TEXT"),
            ("reviews", "TEXT"), ("lead_score", "INTEGER"), ("lead_grade", "TEXT"),
            ("lead_reasons", "TEXT"), ("lead_tags", "TEXT"), ("country", "TEXT"),
            ("web_tech", "TEXT"), ("site_text", "TEXT"), ("is_removed", "INTEGER"),
            ("removed_reason", "TEXT"), ("ai_score", "INTEGER"),
            ("ai_affordability", "TEXT"), ("ai_need", "TEXT"), ("ai_owner", "TEXT"),
            ("ai_verdict", "TEXT"), ("ai_why", "TEXT"), ("ai_pain_points", "TEXT"),
            ("ai_campaign", "TEXT"), ("ai_mode", "TEXT"), ("ai_updated_at", "TEXT"),
        ]
        for col, typ in new_cols:
            if col not in cols:
                try:
                    c.execute(f"ALTER TABLE results ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass
    c.executescript(SCHEMA)
    # Idempotent migration for the jobs table (polygon + persisted scan telemetry)
    job_cols = [
        ("polygon", "TEXT"), ("area_points", "INTEGER"),
        ("lat", "REAL"), ("lng", "REAL"), ("radius_km", "REAL"),
        ("scan_meta", "TEXT"), ("country", "TEXT"),
    ]
    for col, typ in job_cols:
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE ai_missions ADD COLUMN model TEXT")
    except sqlite3.OperationalError:
        pass
    c.commit()
    c.close()


def recover_stale_jobs() -> int:
    """Mark jobs & AI missions left in pending/running from a prior process exit."""
    c = _conn()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    cur = c.execute(
        "UPDATE jobs SET status='interrupted', "
        "error=CASE WHEN error IS NULL OR error='' THEN 'Interrupted by app restart' ELSE error END, "
        "finished_at=? WHERE status IN ('pending', 'running', 'cancelling')",
        (now,),
    )
    n = cur.rowcount
    try:
        c.execute(
            "UPDATE ai_missions SET status='interrupted', "
            "error=CASE WHEN error IS NULL OR error='' THEN 'Interrupted by app restart' ELSE error END, "
            "updated_at=? WHERE status IN ('pending', 'running')",
            (now,),
        )
    except sqlite3.OperationalError:
        pass
    c.commit()
    c.close()
    return n


def insert_job(job: dict) -> None:
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO jobs
           (id,query,location,gl,hl,max_results,proxy,area_scan,status,error,total,scraped,created_at,
            polygon,area_points,lat,lng,radius_km,scan_meta,country)
           VALUES (:id,:query,:location,:gl,:hl,:max_results,:proxy,:area_scan,:status,:error,:total,:scraped,:created_at,
                   :polygon,:area_points,:lat,:lng,:radius_km,:scan_meta,:country)""",
        job,
    )
    c.commit()
    c.close()


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    c = _conn()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id]
    c.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)
    c.commit()
    c.close()


def get_job(job_id: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def list_jobs(limit: int = None, offset: int = 0) -> list:
    c = _conn()
    if limit:
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (int(limit), int(offset)),
        ).fetchall()
    else:
        rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def count_jobs() -> int:
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    c.close()
    return n


def distinct_categories(q: str = None, limit: int = 25) -> list:
    """Distinct categories captured across all results, optionally filtered."""
    c = _conn()
    if q:
        like = f"%{q}%"
        rows = c.execute(
            "SELECT DISTINCT category FROM results "
            "WHERE category IS NOT NULL AND category != '' AND category LIKE ? "
            "ORDER BY category LIMIT ?",
            (like, limit),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT DISTINCT category FROM results "
            "WHERE category IS NOT NULL AND category != '' "
            "ORDER BY category LIMIT ?",
            (limit,),
        ).fetchall()
    c.close()
    return [r["category"] for r in rows]


def rescore_job(job_id: str, config=None) -> int:
    """Recompute lead score / grade / reasons / tags for every result in a job
    using the supplied scoring config. Returns the number of rows updated."""
    from backend.scraper import leadscore

    c = _conn()
    rows = c.execute("SELECT * FROM results WHERE job_id=?", (job_id,)).fetchall()
    n = 0
    for r in rows:
        sr = leadscore.score_row(dict(r), config)
        c.execute(
            "UPDATE results SET lead_score=?, lead_grade=?, lead_reasons=?, lead_tags=? "
            "WHERE id=?",
            (sr.score, sr.grade,
             json.dumps(sr.reasons, ensure_ascii=False),
             json.dumps(sr.tags), r["id"]),
        )
        n += 1
    c.commit()
    c.close()
    return n


def rescore_all(config=None) -> int:
    """Recompute scores for every result across every job."""
    from backend.scraper import leadscore

    c = _conn()
    rows = c.execute("SELECT * FROM results").fetchall()
    n = 0
    for r in rows:
        sr = leadscore.score_row(dict(r), config)
        c.execute(
            "UPDATE results SET lead_score=?, lead_grade=?, lead_reasons=?, lead_tags=? "
            "WHERE id=?",
            (sr.score, sr.grade,
             json.dumps(sr.reasons, ensure_ascii=False),
             json.dumps(sr.tags), r["id"]),
        )
        n += 1
    c.commit()
    c.close()
    return n


def delete_job(job_id: str) -> None:
    c = _conn()
    c.execute("DELETE FROM results WHERE job_id=?", (job_id,))
    c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    c.commit()
    c.close()


def insert_result(job_id: str, r: dict) -> None:
    country = _extract_country(r.get("full_address") or r.get("city_state_zip"))
    payload = {
        **r,
        "job_id": job_id,
        "country": country,
        "site_text": r.get("site_text") or "",
        "is_removed": int(r.get("is_removed") or 0),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO results
           (job_id,cid,name,category,street,city_state_zip,full_address,rating,reviews_count,
            website,phone,email,latitude,longitude,place_id,gid,timezone,thumbnail,is_ad,
            price_level,price_desc,hours,popular_times,menu_url,closed_status,amenities,
            service_options,highlights,popular_for,emails,socials,reviews,lead_score,lead_grade,
            lead_reasons,lead_tags,country,web_tech,site_text,is_removed,raw_json,created_at)
           VALUES (:job_id,:cid,:name,:category,:street,:city_state_zip,:full_address,:rating,:reviews_count,
                   :website,:phone,:email,:latitude,:longitude,:place_id,:gid,:timezone,:thumbnail,:is_ad,
                   :price_level,:price_desc,:hours,:popular_times,:menu_url,:closed_status,:amenities,
                   :service_options,:highlights,:popular_for,:emails,:socials,:reviews,:lead_score,:lead_grade,
                   :lead_reasons,:lead_tags,:country,:web_tech,:site_text,:is_removed,:raw_json,:created_at)""",
        payload,
    )
    c.commit()
    c.close()


def count_results(job_id: str, include_removed: bool = False) -> int:
    c = _conn()
    if include_removed:
        n = c.execute("SELECT COUNT(*) FROM results WHERE job_id=?", (job_id,)).fetchone()[0]
    else:
        n = c.execute(
            "SELECT COUNT(*) FROM results WHERE job_id=? AND COALESCE(is_removed, 0) = 0",
            (job_id,),
        ).fetchone()[0]
    c.close()
    return n


def get_results(job_id: str, limit: int = 1000, offset: int = 0,
                q: str | None = None, filters: dict | None = None) -> dict:
    filters = filters or {}
    conds = ["job_id=?"]
    args: list = [job_id]

    if filters.get("removed_only"):
        conds.append("COALESCE(is_removed, 0) = 1")
    elif not filters.get("include_removed"):
        conds.append("COALESCE(is_removed, 0) = 0")

    if q:
        like = f"%{q}%"
        conds.append("(name LIKE ? OR city_state_zip LIKE ? OR full_address LIKE ?"
                     " OR category LIKE ? OR website LIKE ? OR phone LIKE ? OR email LIKE ?"
                     " OR ai_verdict LIKE ? OR ai_owner LIKE ? OR ai_why LIKE ?)")
        args += [like] * 10

    if filters.get("min_rating") not in (None, ""):
        try:
            conds.append("rating >= ?")
            args.append(float(filters["min_rating"]))
        except (TypeError, ValueError):
            pass

    if filters.get("min_reviews") not in (None, ""):
        try:
            conds.append("reviews_count >= ?")
            args.append(int(filters["min_reviews"]))
        except (TypeError, ValueError):
            pass

    if filters.get("min_ai_score") not in (None, ""):
        try:
            conds.append("ai_score >= ?")
            args.append(int(filters["min_ai_score"]))
        except (TypeError, ValueError):
            pass

    aff = filters.get("affordability")
    if aff:
        affs = [aff] if isinstance(aff, str) else [a for a in aff if a]
        if affs:
            placeholders = ",".join("?" * len(affs))
            conds.append(f"LOWER(ai_affordability) IN ({placeholders})")
            args += [a.strip().lower() for a in affs]

    verdict = filters.get("ai_verdict")
    if verdict:
        verdicts = [verdict] if isinstance(verdict, str) else [v for v in verdict if v]
        if verdicts:
            ors = " OR ".join("LOWER(ai_verdict) LIKE ?" for _ in verdicts)
            conds.append(f"({ors})")
            args += [f"%{v.strip().lower()}%" for v in verdicts]

    if filters.get("ai_analyzed_only"):
        conds.append("ai_score IS NOT NULL")

    cats = filters.get("category") or []
    if isinstance(cats, str):
        cats = [cats]
    cats = [x for x in cats if x]
    if cats:
        ors = " OR ".join("category LIKE ?" for _ in cats)
        conds.append(f"({ors})")
        args += [f"%{cat}%" for cat in cats]

    locs = filters.get("location") or []
    if isinstance(locs, str):
        locs = [locs]
    locs = [l for l in locs if l]
    if locs:
        # Multiple location selections are OR'd within the group (a result
        # matches if it's in ANY of the chosen areas), then AND'd with the rest.
        ors = " OR ".join("(city_state_zip LIKE ? OR full_address LIKE ?)" for _ in locs)
        conds.append(f"({ors})")
        for loc in locs:
            args += [f"%{loc}%", f"%{loc}%"]

    countries = filters.get("country") or []
    if isinstance(countries, str):
        countries = [countries]
    countries = [c for c in countries if c]
    if countries:
        # Exact match against the stored, normalised `country` column.
        placeholders = ",".join("?" * len(countries))
        conds.append(f"country IN ({placeholders})")
        args += countries

    if filters.get("has_email"):
        conds.append("(email != '' OR emails LIKE '%@%')")
    if filters.get("has_social"):
        conds.append("socials LIKE 'http%'")
    if filters.get("has_website"):
        conds.append("website != ''")
    if filters.get("has_phone"):
        conds.append("phone != ''")
    if filters.get("has_hours"):
        conds.append("hours != ''")
    if filters.get("has_menu"):
        conds.append("menu_url != ''")
    if filters.get("has_reviews"):
        conds.append("(reviews_count IS NOT NULL AND reviews_count > 0)")
    if filters.get("hot_only"):
        conds.append("lead_grade = 'Hot'")

    sort = filters.get("sort", "default")
    if sort == "rating_desc":
        order = "rating DESC, rowid"
    elif sort == "reviews_desc":
        order = "reviews_count DESC, rowid"
    elif sort == "rating_asc":
        order = "rating ASC, rowid"
    elif sort == "lead_desc":
        order = "lead_score DESC, rowid"
    elif sort == "lead_asc":
        order = "lead_score ASC, rowid"
    elif sort == "ai_desc":
        order = "COALESCE(ai_score, -1) DESC, lead_score DESC, rowid"
    elif sort == "ai_asc":
        order = "COALESCE(ai_score, 999) ASC, lead_score ASC, rowid"
    else:
        order = "rowid"

    where = " WHERE " + " AND ".join(conds)
    c = _conn()
    total = c.execute(f"SELECT COUNT(*) FROM results {where}", args).fetchone()[0]
    removed_count = c.execute(
        "SELECT COUNT(*) FROM results WHERE job_id=? AND COALESCE(is_removed, 0) = 1",
        (job_id,),
    ).fetchone()[0]
    rows = c.execute(
        f"SELECT * FROM results {where} ORDER BY {order} LIMIT ? OFFSET ?",
        args + [limit, offset],
    ).fetchall()
    c.close()
    return {"items": [dict(r) for r in rows], "total": total, "removed_count": removed_count}


def previous_job_for(job_id: str) -> dict | None:
    """Most recent *completed* job (other than `job_id`) with the same
    normalized query+location — the baseline for "new since last scan"."""
    job = get_job(job_id)
    if not job:
        return None
    q = (job.get("query") or "").strip().lower()
    loc = (job.get("location") or "").strip().lower()
    c = _conn()
    row = c.execute(
        "SELECT * FROM jobs WHERE status='completed' AND id != ? "
        "AND lower(trim(query))=? AND lower(trim(location))=? "
        "ORDER BY created_at DESC LIMIT 1",
        (job_id, q, loc),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def compare_jobs(cur_id: str, base_id: str) -> dict:
    """Diff two jobs by CID: new, removed, and rating/review changes."""
    a = get_results(base_id, limit=100000)["items"]
    b = get_results(cur_id, limit=100000)["items"]
    a_map = {r["cid"]: r for r in a if r.get("cid")}
    b_map = {r["cid"]: r for r in b if r.get("cid")}

    new = [b_map[c] for c in b_map if c not in a_map]
    removed = [a_map[c] for c in a_map if c not in b_map]
    changed = []
    for c, br in b_map.items():
        ar = a_map.get(c)
        if not ar:
            continue
        ra, rb = ar.get("rating"), br.get("rating")
        ca, cb = ar.get("reviews_count") or 0, br.get("reviews_count") or 0
        if (ra != rb) or (ca != cb):
            changed.append({
                "cid": c, "name": br.get("name"),
                "rating_a": ra, "rating_b": rb,
                "reviews_a": ca, "reviews_b": cb,
            })
    return {"new": new, "removed": removed, "changed": changed}


def _extract_area(addr: str | None) -> str | None:
    """Best-effort locality/area from a free-form address: the 2nd comma
    segment (street, AREA, city, ...). Good enough to drive location filters."""
    if not addr:
        return None
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else None


def _extract_country(addr: str | None) -> str | None:
    """Normalized country from a free-form address.

    International results end with the country name (e.g. '…, Nigeria'). US
    results usually end with 'State ZIP' (e.g. '…, NC 27705') and omit 'USA',
    so we normalise those to 'United States' for consistent filtering/facets.
    """
    if not addr:
        return None
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) < 2:
        return None
    last = parts[-1]
    if last in US_STATES:
        return "United States"
    if re.match(r"^[A-Z]{2}\s?\d{4,10}(-\d{1,8})?$", last):  # "NC 27705"
        return "United States"
    if re.match(r"^\d{4,10}(-\d{1,8})?$", last):             # bare postal code
        return "United States"
    if last.isdigit():
        return None
    return last


def backfill_countries() -> int:
    """Compute + store the `country` column for any rows missing it (e.g.
    results scraped before the column existed). Returns rows updated."""
    c = _conn()
    rows = c.execute(
        "SELECT id, full_address, city_state_zip FROM results WHERE country IS NULL OR country = ''"
    ).fetchall()
    n = 0
    for r in rows:
        country = _extract_country(r["full_address"] or r["city_state_zip"])
        c.execute("UPDATE results SET country=? WHERE id=?", (country, r["id"]))
        n += 1
    c.commit()
    c.close()
    return n


def get_facets(job_id: str) -> dict:
    """Aggregate filterable facets for a job: detected areas + presence counts."""
    from collections import Counter
    c = _conn()
    rows = c.execute(
        "SELECT full_address, city_state_zip, country, rating, reviews_count, website, phone,"
        " email, emails, socials, hours, menu_url, ai_score, ai_verdict "
        "FROM results WHERE job_id=? AND COALESCE(is_removed, 0) = 0", (job_id,),
    ).fetchall()
    removed_count = c.execute(
        "SELECT COUNT(*) FROM results WHERE job_id=? AND COALESCE(is_removed, 0) = 1",
        (job_id,),
    ).fetchone()[0]
    area_counter: Counter = Counter()
    counts = {
        "total": len(rows), "rated": 0, "with_email": 0, "with_social": 0,
        "with_website": 0, "with_phone": 0, "with_hours": 0, "with_menu": 0,
        "with_reviews": 0, "without_website": 0, "without_email": 0,
        "ai_analyzed": 0, "ai_strong_fit": 0, "removed_count": removed_count,
        "sum_rating": 0, "sum_reviews": 0,
    }
    for r in rows:
        area = _extract_area(r["full_address"]) or _extract_area(r["city_state_zip"])
        if area:
            area_counter[area] += 1
        if r["email"] or (r["emails"] and "@" in (r["emails"] or "")):
            counts["with_email"] += 1
        else:
            counts["without_email"] += 1
        if r["socials"] and "http" in (r["socials"] or ""):
            counts["with_social"] += 1
        if r["website"]:
            counts["with_website"] += 1
        else:
            counts["without_website"] += 1
        if r["phone"]:
            counts["with_phone"] += 1
        if r["hours"]:
            counts["with_hours"] += 1
        if r["menu_url"]:
            counts["with_menu"] += 1
        if r["reviews_count"]:
            counts["with_reviews"] += 1
        if r["ai_score"] is not None:
            counts["ai_analyzed"] += 1
            if "strong" in (r["ai_verdict"] or "").lower():
                counts["ai_strong_fit"] += 1
        if r["rating"] is not None:
            counts["rated"] += 1
            counts["sum_rating"] += r["rating"]
        if r["reviews_count"]:
            counts["sum_reviews"] += r["reviews_count"]
    counts["avg_rating"] = round(counts["sum_rating"] / counts["rated"], 2) if counts["rated"] else None
    counts["avg_reviews"] = round(counts["sum_reviews"] / counts["total"], 1) if counts["total"] else 0
    del counts["sum_rating"]
    del counts["sum_reviews"]
    areas = [{"value": a, "count": n} for a, n in area_counter.most_common(40)]
    cc = c.execute(
        "SELECT country, COUNT(*) AS n FROM results WHERE job_id=? AND COALESCE(is_removed, 0) = 0 "
        "AND country IS NOT NULL AND country != '' GROUP BY country ORDER BY n DESC LIMIT 60",
        (job_id,),
    ).fetchall()
    countries = [{"value": r["country"], "count": r["n"]} for r in cc]
    c.close()
    return {"areas": areas, "countries": countries, "counts": counts}


# ─── AI Lead Management (Soft-Delete / Updates) ───────────────────────────────

def get_result_by_cid(job_id: str, cid: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM results WHERE job_id=? AND cid=?", (job_id, cid)).fetchone()
    c.close()
    return dict(row) if row else None


def get_all_job_results(job_id: str, include_removed: bool = False) -> list[dict]:
    c = _conn()
    cond = "job_id=?" if include_removed else "job_id=? AND COALESCE(is_removed, 0) = 0"
    rows = c.execute(f"SELECT * FROM results WHERE {cond} ORDER BY rowid", (job_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def remove_leads(job_id: str, cids: list[str], reason: str = "") -> int:
    clean = [str(cid).strip() for cid in (cids or []) if str(cid).strip()]
    if not clean:
        return 0
    c = _conn()
    placeholders = ",".join("?" * len(clean))
    cur = c.execute(
        f"UPDATE results SET is_removed=1, removed_reason=? "
        f"WHERE job_id=? AND cid IN ({placeholders}) AND COALESCE(is_removed, 0) = 0",
        [reason or "Filtered out by AI"] + [job_id] + clean,
    )
    n = cur.rowcount
    c.commit()
    c.close()
    return n


def restore_leads(job_id: str, cids: list[str] | None = None) -> int:
    c = _conn()
    if cids:
        clean = [str(cid).strip() for cid in cids if str(cid).strip()]
        if not clean:
            c.close()
            return 0
        placeholders = ",".join("?" * len(clean))
        cur = c.execute(
            f"UPDATE results SET is_removed=0, removed_reason='' "
            f"WHERE job_id=? AND cid IN ({placeholders}) AND COALESCE(is_removed, 0) = 1",
            [job_id] + clean,
        )
    else:
        cur = c.execute(
            "UPDATE results SET is_removed=0, removed_reason='' "
            "WHERE job_id=? AND COALESCE(is_removed, 0) = 1",
            (job_id,),
        )
    n = cur.rowcount
    c.commit()
    c.close()
    return n


def update_result_site_text(job_id: str, cid: str, site_text: str, extra: dict | None = None) -> None:
    """Cache scraped website text (and optional email/socials/web_tech) back into results."""
    c = _conn()
    fields: dict = {"site_text": (site_text or "")[:6000]}
    if extra:
        for k in ("email", "emails", "socials", "web_tech"):
            if extra.get(k):
                fields[k] = extra[k] if isinstance(extra[k], str) else json.dumps(extra[k])
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id, cid]
    c.execute(f"UPDATE results SET {sets} WHERE job_id=? AND cid=?", vals)
    c.commit()
    c.close()


def update_lead_ai(job_id: str, cid: str, ai_data: dict) -> bool:
    """Persist structured AI qualification & outreach fields on a lead."""
    pain = ai_data.get("ai_pain_points", ai_data.get("pain_points"))
    if isinstance(pain, (list, dict)):
        pain_str = json.dumps(pain, ensure_ascii=False)
    else:
        pain_str = str(pain or "")

    campaign = ai_data.get("ai_campaign", ai_data.get("campaign"))
    if isinstance(campaign, (dict, list)):
        campaign_str = json.dumps(campaign, ensure_ascii=False)
    else:
        campaign_str = str(campaign or "")

    score_raw = ai_data.get("ai_score")
    try:
        score = max(0, min(100, int(round(float(score_raw))))) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    c = _conn()
    cur = c.execute(
        """UPDATE results SET
           ai_score=COALESCE(?, ai_score),
           ai_affordability=CASE WHEN ? != '' THEN ? ELSE ai_affordability END,
           ai_need=CASE WHEN ? != '' THEN ? ELSE ai_need END,
           ai_owner=CASE WHEN ? != '' THEN ? ELSE ai_owner END,
           ai_verdict=CASE WHEN ? != '' THEN ? ELSE ai_verdict END,
           ai_why=CASE WHEN ? != '' THEN ? ELSE ai_why END,
           ai_pain_points=CASE WHEN ? != '' THEN ? ELSE ai_pain_points END,
           ai_campaign=CASE WHEN ? != '' THEN ? ELSE ai_campaign END,
           ai_mode=CASE WHEN ? != '' THEN ? ELSE ai_mode END,
           ai_updated_at=?
           WHERE job_id=? AND cid=?""",
        (
            score,
            str(ai_data.get("ai_affordability") or ai_data.get("affordability") or ""),
            str(ai_data.get("ai_affordability") or ai_data.get("affordability") or ""),
            str(ai_data.get("ai_need") or ai_data.get("need") or ""),
            str(ai_data.get("ai_need") or ai_data.get("need") or ""),
            str(ai_data.get("ai_owner") or ai_data.get("owner") or ""),
            str(ai_data.get("ai_owner") or ai_data.get("owner") or ""),
            str(ai_data.get("ai_verdict") or ai_data.get("verdict") or ""),
            str(ai_data.get("ai_verdict") or ai_data.get("verdict") or ""),
            str(ai_data.get("ai_why") or ai_data.get("why") or ""),
            str(ai_data.get("ai_why") or ai_data.get("why") or ""),
            pain_str, pain_str,
            campaign_str, campaign_str,
            str(ai_data.get("ai_mode") or ai_data.get("mode") or ""),
            str(ai_data.get("ai_mode") or ai_data.get("mode") or ""),
            now, job_id, cid,
        ),
    )
    ok = cur.rowcount > 0
    c.commit()
    c.close()
    return ok


# ─── Saved Offer Profiles (ai_offers) ─────────────────────────────────────────

def list_offers() -> list[dict]:
    c = _conn()
    rows = c.execute("SELECT * FROM ai_offers ORDER BY updated_at DESC, created_at DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_offer(offer_id: str) -> dict | None:
    if not offer_id:
        return None
    c = _conn()
    row = c.execute("SELECT * FROM ai_offers WHERE id=?", (offer_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def save_offer(payload: dict) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    offer_id = (payload.get("id") or "").strip() or f"off_{uuid.uuid4().hex[:10]}"
    name = (payload.get("name") or "My Service Offer").strip()[:120]
    service_type = (payload.get("service_type") or "").strip()[:240]
    min_budget = (payload.get("min_budget") or "").strip()[:120]
    target_niche = (payload.get("target_niche") or "").strip()[:240]
    pitch_notes = (payload.get("pitch_notes") or "").strip()[:2000]
    mode_id = (payload.get("mode_id") or "custom").strip()[:60]
    c = _conn()
    existing = c.execute("SELECT created_at FROM ai_offers WHERE id=?", (offer_id,)).fetchone()
    created_at = existing["created_at"] if existing else now
    c.execute(
        """INSERT OR REPLACE INTO ai_offers
           (id, name, service_type, min_budget, target_niche, pitch_notes, mode_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (offer_id, name, service_type, min_budget, target_niche, pitch_notes, mode_id, created_at, now),
    )
    c.commit()
    row = c.execute("SELECT * FROM ai_offers WHERE id=?", (offer_id,)).fetchone()
    c.close()
    return dict(row)


def delete_offer(offer_id: str) -> bool:
    c = _conn()
    cur = c.execute("DELETE FROM ai_offers WHERE id=?", (offer_id,))
    ok = cur.rowcount > 0
    c.commit()
    c.close()
    return ok


# ─── AI Missions & Conversations (ai_missions / ai_messages) ───────────────────

def create_mission(goal: str, mode_id: str = "custom", offer_id: str = "",
                   job_id: str = "", title: str = "", model: str = "") -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    mid = f"mis_{uuid.uuid4().hex[:10]}"
    clean_goal = (goal or "").strip()
    clean_title = (title or clean_goal[:70] or "AI Autopilot Mission").strip()
    c = _conn()
    c.execute(
        """INSERT INTO ai_missions
           (id, title, goal, mode_id, offer_id, job_id, model, status, summary, error, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, clean_title, clean_goal, mode_id or "custom", offer_id or "",
         job_id or "", model or "", "pending", "", "", now, now),
    )
    c.commit()
    row = c.execute("SELECT * FROM ai_missions WHERE id=?", (mid,)).fetchone()
    c.close()
    return dict(row)


def update_mission(mission_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    c = _conn()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [mission_id]
    c.execute(f"UPDATE ai_missions SET {sets} WHERE id=?", vals)
    c.commit()
    c.close()


def get_mission(mission_id: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM ai_missions WHERE id=?", (mission_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def list_missions(limit: int = 40) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM ai_missions ORDER BY updated_at DESC, created_at DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def delete_mission(mission_id: str) -> bool:
    c = _conn()
    c.execute("DELETE FROM ai_messages WHERE mission_id=?", (mission_id,))
    cur = c.execute("DELETE FROM ai_missions WHERE id=?", (mission_id,))
    ok = cur.rowcount > 0
    c.commit()
    c.close()
    return ok


def add_mission_message(mission_id: str, role: str, content: str = "",
                        tool_name: str = "", tool_args=None, tool_result=None,
                        job_id: str = "") -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    args_s = json.dumps(tool_args, ensure_ascii=False) if isinstance(tool_args, (dict, list)) else str(tool_args or "")
    res_s = json.dumps(tool_result, ensure_ascii=False) if isinstance(tool_result, (dict, list)) else str(tool_result or "")
    c = _conn()
    cur = c.execute(
        """INSERT INTO ai_messages
           (mission_id, role, content, tool_name, tool_args, tool_result, job_id, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (mission_id, role, str(content or ""), tool_name or "", args_s, res_s, job_id or "", now),
    )
    msg_id = cur.lastrowid
    c.execute("UPDATE ai_missions SET updated_at=? WHERE id=?", (now, mission_id))
    c.commit()
    row = c.execute("SELECT * FROM ai_messages WHERE id=?", (msg_id,)).fetchone()
    c.close()
    return dict(row)


def list_mission_messages(mission_id: str, limit: int = 250) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM ai_messages WHERE mission_id=? ORDER BY id ASC LIMIT ?",
        (mission_id, int(limit)),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ─── Saved Shortlists (saved_lists / saved_list_items) ────────────────────────

def create_list(name: str, description: str = "") -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    lid = f"lst_{uuid.uuid4().hex[:10]}"
    clean_name = (name or "Shortlist").strip()[:120]
    c = _conn()
    c.execute(
        "INSERT INTO saved_lists (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
        (lid, clean_name, (description or "").strip()[:500], now, now),
    )
    c.commit()
    row = c.execute("SELECT * FROM saved_lists WHERE id=?", (lid,)).fetchone()
    c.close()
    out = dict(row)
    out["item_count"] = 0
    return out


def list_saved_lists() -> list[dict]:
    c = _conn()
    rows = c.execute(
        """SELECT l.*, COUNT(i.id) AS item_count
           FROM saved_lists l
           LEFT JOIN saved_list_items i ON i.list_id = l.id
           GROUP BY l.id
           ORDER BY l.updated_at DESC, l.created_at DESC"""
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_saved_list(list_id: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM saved_lists WHERE id=?", (list_id,)).fetchone()
    if not row:
        c.close()
        return None
    items = c.execute(
        "SELECT * FROM saved_list_items WHERE list_id=? ORDER BY COALESCE(ai_score, -1) DESC, id DESC",
        (list_id,),
    ).fetchall()
    c.close()
    out = dict(row)
    out["items"] = [dict(i) for i in items]
    out["item_count"] = len(out["items"])
    return out


def delete_list(list_id: str) -> bool:
    c = _conn()
    c.execute("DELETE FROM saved_list_items WHERE list_id=?", (list_id,))
    cur = c.execute("DELETE FROM saved_lists WHERE id=?", (list_id,))
    ok = cur.rowcount > 0
    c.commit()
    c.close()
    return ok


def add_list_items(list_id: str, leads: list[dict], notes: str = "") -> int:
    if not leads:
        return 0
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    c = _conn()
    added = 0
    for lead in leads:
        cid = str(lead.get("cid") or lead.get("place_id") or lead.get("name") or "").strip()
        if not cid:
            continue
        existing = c.execute(
            "SELECT id, status, notes FROM saved_list_items WHERE list_id=? AND cid=?",
            (list_id, cid),
        ).fetchone()
        status = existing["status"] if existing and existing["status"] else "New"
        item_notes = (notes or (existing["notes"] if existing else "") or "").strip()
        snap = json.dumps(lead, ensure_ascii=False)
        camp = lead.get("ai_campaign")
        if isinstance(camp, (dict, list)):
            camp = json.dumps(camp, ensure_ascii=False)
        c.execute(
            """INSERT OR REPLACE INTO saved_list_items
               (list_id, job_id, cid, name, category, full_address, phone, email, emails,
                website, rating, reviews_count, lead_score, ai_score, ai_affordability,
                ai_verdict, ai_why, ai_campaign, notes, status, snapshot_json, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                list_id,
                str(lead.get("job_id") or ""),
                cid,
                str(lead.get("name") or ""),
                str(lead.get("category") or ""),
                str(lead.get("full_address") or lead.get("city_state_zip") or ""),
                str(lead.get("phone") or ""),
                str(lead.get("email") or ""),
                str(lead.get("emails") or ""),
                str(lead.get("website") or ""),
                lead.get("rating"),
                lead.get("reviews_count"),
                lead.get("lead_score"),
                lead.get("ai_score"),
                str(lead.get("ai_affordability") or ""),
                str(lead.get("ai_verdict") or ""),
                str(lead.get("ai_why") or ""),
                str(camp or ""),
                item_notes,
                status,
                snap,
                now,
            ),
        )
        added += 1
    c.execute("UPDATE saved_lists SET updated_at=? WHERE id=?", (now, list_id))
    c.commit()
    c.close()
    return added


def list_saved_items(list_id: str) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM saved_list_items WHERE list_id=? ORDER BY COALESCE(ai_score, -1) DESC, id DESC",
        (list_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def update_list_item(item_id: int, status: str | None = None, notes: str | None = None) -> dict | None:
    fields: dict = {}
    if status is not None:
        fields["status"] = str(status).strip()[:40] or "New"
    if notes is not None:
        fields["notes"] = str(notes).strip()[:2000]
    if not fields:
        return None
    c = _conn()
    sets = ", ".join(f"{k}=?" for k in fields)
    c.execute(f"UPDATE saved_list_items SET {sets} WHERE id=?", list(fields.values()) + [int(item_id)])
    row = c.execute("SELECT * FROM saved_list_items WHERE id=?", (int(item_id),)).fetchone()
    c.commit()
    c.close()
    return dict(row) if row else None


def delete_list_item(item_id: int) -> bool:
    c = _conn()
    cur = c.execute("DELETE FROM saved_list_items WHERE id=?", (int(item_id),))
    ok = cur.rowcount > 0
    c.commit()
    c.close()
    return ok
