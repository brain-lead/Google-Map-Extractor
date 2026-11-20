"""Proxy pool: parse, store, auto-test, and rotate proxies.

Supported input formats (one per line, or comma-separated):
  - 1.2.3.4:8080                 -> http://1.2.3.4:8080
  - 1.2.3.4:8080:user:pass      -> http://user:pass@1.2.3.4:8080
  - user:pass@1.2.3.4:8080      -> http://user:pass@1.2.3.4:8080
  - http://... / socks5://...    -> kept as-is
"""
import json
import re
import time
import asyncio
from pathlib import Path
from backend.config import DATA_DIR
from backend.scraper.client import make_session, BASE, base_headers


PROXIES_FILE = DATA_DIR / "proxies.json"
_idx = 0
_FAIL_STREAK: dict[str, int] = {}
_COOLDOWN_UNTIL: dict[str, float] = {}


def _load() -> list:
    if PROXIES_FILE.exists():
        try:
            return json.loads(PROXIES_FILE.read_text())
        except Exception:
            return []
    return []


def _save(lst: list) -> None:
    PROXIES_FILE.write_text(json.dumps(lst, indent=2))


def normalize(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    if re.match(r"^(https?|socks[45]h?)://", raw, re.I):
        return raw
    if "@" in raw:  # user:pass@host:port
        return "http://" + raw
    parts = [p for p in raw.split(":") if p != ""]
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    if len(parts) == 4:
        ip, port, user, pw = parts
        return f"http://{user}:{pw}@{ip}:{port}"
    return None


def add_proxies(text: str) -> dict:
    """Parse a bulk string (newline/comma/space separated) and store new proxies."""
    added = 0
    lst = _load()
    seen = {e["url"] for e in lst}
    for chunk in re.split(r"[\s,]+", text or ""):
        url = normalize(chunk)
        if not url:
            continue
        if url in seen:
            continue
        lst.append({
            "url": url,
            "raw": chunk,
            "status": "untested",
            "latency": None,
            "error": None,
            "last_tested": None,
        })
        seen.add(url)
        added += 1
    _save(lst)
    return {"added": added, "total": len(lst)}


async def test_proxy(url: str) -> dict:
    session = make_session(cookies={}, proxies=url)
    t = time.time()
    try:
        resp = await session.get("https://www.google.com", headers=base_headers(), timeout=10)
        latency = int((time.time() - t) * 1000)
        ok = resp.status_code == 200 and len(resp.content) > 200
        return {"ok": ok, "latency": latency,
                "error": None if ok else f"status {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "latency": None, "error": str(e)[:140]}
    finally:
        await session.close()


async def test_all() -> list:
    lst = _load()
    sem = asyncio.Semaphore(20)

    async def _test_one(e):
        async with sem:
            r = await test_proxy(e["url"])
        e["status"] = "working" if r["ok"] else "failed"
        e["latency"] = r["latency"]
        e["error"] = r["error"]
        e["last_tested"] = time.time()

    # Test every proxy concurrently (bounded) instead of one-by-one, so a pool
    # of N proxies finishes in roughly one request's latency, not N x latency.
    await asyncio.gather(*(_test_one(e) for e in lst))
    _save(lst)
    return lst


def list_proxies() -> list:
    return _load()


def clear_proxies() -> dict:
    _save([])
    return {"cleared": True}


def report_proxy(url: str | None, ok: bool) -> None:
    """Track consecutive proxy failures in memory and cool down flaky proxies."""
    if not url:
        return
    if ok:
        _FAIL_STREAK.pop(url, None)
        _COOLDOWN_UNTIL.pop(url, None)
        return
    streak = _FAIL_STREAK.get(url, 0) + 1
    _FAIL_STREAK[url] = streak
    if streak >= 3:
        _COOLDOWN_UNTIL[url] = time.time() + 90.0


def get_proxy():
    """Round-robin a *working* proxy (skipping cooled-down proxies), else None."""
    global _idx
    lst = _load()
    if not lst:
        return None
    working = [e for e in lst if e.get("status") == "working"]
    if not working:
        return None
    now = time.time()
    healthy = [e for e in working if _COOLDOWN_UNTIL.get(e["url"], 0.0) <= now]
    pool = healthy or working
    if not healthy:
        _COOLDOWN_UNTIL.clear()
        _FAIL_STREAK.clear()
    p = pool[_idx % len(pool)]
    _idx += 1
    return p["url"]
