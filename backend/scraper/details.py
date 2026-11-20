"""Place-details endpoint: /maps/preview/place -> full business record (j[6])."""
import json
from backend.scraper import pb
from backend.scraper.client import make_session, get_json, strip_xssi, BASE, StaleSessionError
from backend.scraper.fields import build_business


def parse_details_response(data: list, cid: str, gid: str = "", is_ad: bool = False):
    try:
        rec = data[6]
    except Exception:
        return None
    return build_business(rec, cid, gid=gid, is_ad=is_ad)


async def fetch_details(cid: str, gl: str = "us", hl: str = "en",
                        cookies: dict | None = None, proxies: str | None = None) -> object | None:
    session = make_session(cookies=cookies, proxies=proxies)
    try:
        p = pb.PLACE_PB.replace(pb.PLACE_CID_TOKEN, "!1s" + cid)
        url = f"{BASE}/maps/preview/place?authuser=0&hl={hl}&gl={gl}&pb={p}"
        body, ok = await get_json(session, url,
                                  referer="https://www.google.com/maps")
    finally:
        await session.close()

    if not ok:
        raise RuntimeError(f"details endpoint returned non-200 for {cid}")
    if body.lstrip()[:1] == b"<":
        raise StaleSessionError("Google returned HTML consent/block page on details")

    text = strip_xssi(body)
    try:
        data = json.loads(text)
    except Exception as e:
        raise RuntimeError(f"invalid details JSON for {cid}: {e}")
    return parse_details_response(data, cid)
