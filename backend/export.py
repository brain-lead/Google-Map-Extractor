"""Export scraped results to CSV / Excel / JSON / Google Sheets / CRM-mapped CSV."""
import csv
import io
import json
import re
from urllib.parse import urlparse

from backend import db

COLUMNS = [
    "name", "category", "rating", "reviews_count", "price_level", "price_desc",
    "website", "phone", "email", "emails", "socials",
    "street", "city_state_zip", "full_address", "country", "hours", "menu_url",
    "closed_status", "amenities", "service_options", "highlights", "popular_for",
    "latitude", "longitude", "cid", "place_id", "gid", "timezone", "thumbnail",
    "is_ad", "reviews", "lead_score", "lead_grade", "lead_reasons", "lead_tags",
    "ai_score", "ai_affordability", "ai_need", "ai_owner", "ai_verdict",
    "ai_why", "ai_pain_points", "ai_subject", "ai_icebreaker", "ai_call_script",
]

SHORTLIST_COLUMNS = ["list_status", "list_notes"] + COLUMNS


def _parse_json_val(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if not raw or not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _enrich_row(r: dict) -> dict:
    """Unpack AI campaign & pain-points JSON into flat export columns."""
    out = dict(r)
    camp = _parse_json_val(out.get("ai_campaign"))
    if isinstance(camp, dict):
        out["ai_subject"] = str(camp.get("email_subject") or camp.get("subject") or "")
        out["ai_icebreaker"] = str(
            camp.get("icebreaker") or camp.get("opening_hook") or camp.get("email_opener") or ""
        )
        out["ai_call_script"] = str(camp.get("call_opener") or camp.get("call_script") or "")
    else:
        out.setdefault("ai_subject", "")
        out.setdefault("ai_icebreaker", "")
        out.setdefault("ai_call_script", "")

    pains = _parse_json_val(out.get("ai_pain_points"))
    if isinstance(pains, list):
        out["ai_pain_points"] = "; ".join(str(x) for x in pains if x)

    for k in ("ai_score", "ai_affordability", "ai_need", "ai_owner", "ai_verdict", "ai_why", "ai_pain_points"):
        if out.get(k) is None:
            out[k] = ""
    return out


def get_rows(job_id: str, q: str | None = None, filters: dict | None = None) -> list:
    data = db.get_results(job_id, limit=100000, q=q, filters=filters)
    return [_enrich_row(r) for r in data["items"]]


def _rows_to_csv(rows: list[dict], columns: list[str] | None = None) -> bytes:
    cols = columns or COLUMNS
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def _rows_to_xlsx(rows: list[dict], columns: list[str] | None = None, title: str = "Results") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    cols = columns or COLUMNS
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(cols)
    head_fill = PatternFill("solid", fgColor="1F2937")
    head_font = Font(bold=True, color="FFFFFF")
    for c in range(1, len(cols) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append([r.get(c, "") if r.get(c) is not None else "" for c in cols])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_csv(job_id: str, q: str | None = None, filters: dict | None = None) -> bytes:
    return _rows_to_csv(get_rows(job_id, q, filters))


def to_json(job_id: str, q: str | None = None, filters: dict | None = None) -> bytes:
    rows = get_rows(job_id, q, filters)
    return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")


def to_xlsx(job_id: str, q: str | None = None, filters: dict | None = None) -> bytes:
    return _rows_to_xlsx(get_rows(job_id, q, filters), title="Results")


def to_google_sheets(job_id: str, creds_path: str, sheet_name: str = "Maps Results",
                    q: str | None = None, filters: dict | None = None) -> str:
    """Append results to a Google Sheet (requires user-supplied creds.json
    from a Google Cloud OAuth client). Returns the spreadsheet URL."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    rows = get_rows(job_id, q, filters)
    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    # create a new spreadsheet
    body = {"properties": {"title": sheet_name}}
    sheet = service.spreadsheets().create(body=body).execute()
    sid = sheet["spreadsheetId"]
    values = [COLUMNS] + [[r.get(c, "") for c in COLUMNS] for r in rows]
    service.spreadsheets().values().update(
        spreadsheetId=sid, range="A1",
        valueInputOption="RAW", body={"values": values}
    ).execute()
    return f"https://docs.google.com/spreadsheets/d/{sid}"


# --------------------------------------------------------------------------
# CRM-mapped exports (column remapping for popular CRM import templates).
# --------------------------------------------------------------------------
# Header order for each supported CRM. Values are built from one shared
# "base" dict (below) so a single row-mapping covers every template.
CRM_HEADERS = {
    "hubspot": ["Company name", "Phone", "Website", "Domain", "Address",
                "City", "State/Region", "Zip code", "Email", "Industry",
                "Lead Status", "Description"],
    "salesforce": ["Company", "First Name", "Last Name", "Title", "Phone",
                   "Email", "Website", "Street", "City", "State", "PostalCode",
                   "Country", "Rating", "Lead Source", "Description"],
    "zoho": ["Company", "First Name", "Last Name", "Title", "Phone", "Email",
             "Website", "Street", "City", "State", "Zip Code", "Country",
             "Lead Source", "Rating", "Description"],
}
CRM_CHOICES = ("hubspot", "salesforce", "zoho")


def _email_of(r: dict) -> str:
    e = (r.get("email") or "").strip()
    if e:
        return e
    try:
        em = json.loads(r.get("emails") or "[]")
        if em:
            return str(em[0])
    except Exception:
        pass
    return ""


def _domain_of(r: dict) -> str:
    w = (r.get("website") or "").strip()
    if not w:
        return ""
    if "://" not in w:
        w = "http://" + w
    net = urlparse(w).netloc
    return net[4:] if net.startswith("www.") else net


def _city_state_zip(csz) -> tuple:
    city = state = zipc = ""
    if not csz:
        return city, state, zipc
    parts = [p.strip() for p in str(csz).split(",")]
    city = parts[0] if parts else ""
    if len(parts) > 1:
        rest = parts[1]
        m = re.search(r"\d{4,10}", rest)
        if m:
            zipc = m.group(0)
        state = rest.replace(zipc, "").strip(" ,")
    return city, state, zipc


def _split_name(name) -> tuple:
    name = (name or "").strip()
    if not name:
        return "", ""
    toks = name.split()
    if len(toks) == 1:
        return "", toks[0]
    return toks[0], " ".join(toks[1:])


def _contact_names(r: dict) -> tuple:
    owner = (r.get("ai_owner") or "").strip()
    if owner and owner.lower() not in {"unknown", "n/a", "none", "not found", "owner", "team"}:
        return _split_name(owner)
    return _split_name(r.get("name"))


def _describe(r: dict) -> str:
    parts = []
    if r.get("ai_verdict"):
        score = f" ({r.get('ai_score')}/100)" if r.get("ai_score") not in (None, "") else ""
        parts.append(f"AI Verdict: {r['ai_verdict']}{score}")
    if r.get("ai_why"):
        parts.append(f"Why: {r['ai_why']}")
    if r.get("ai_icebreaker"):
        parts.append(f"Icebreaker: {r['ai_icebreaker']}")
    if r.get("list_notes"):
        parts.append(f"Notes: {r['list_notes']}")
    try:
        reasons = json.loads(r.get("lead_reasons") or "[]")
    except Exception:
        reasons = []
    if reasons:
        parts.append("Signals: " + "; ".join(str(x) for x in reasons))
    return " | ".join(parts)


def _rows_to_crm_csv(rows: list[dict], crm: str = "hubspot") -> bytes:
    crm = (crm or "hubspot").lower()
    if crm not in CRM_CHOICES:
        crm = "hubspot"
    headers = CRM_HEADERS[crm]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        city, state, zipc = _city_state_zip(r.get("city_state_zip"))
        fn, ln = _contact_names(r)
        base = {
            # shared keys — DictWriter picks only the headers this CRM needs
            "Company": r.get("name", ""),
            "Company name": r.get("name", ""),
            "First Name": fn,
            "Last Name": ln,
            "Title": "Owner" if (r.get("ai_owner") or "").strip() else "",
            "Phone": r.get("phone", ""),
            "Email": _email_of(r),
            "Website": r.get("website", ""),
            "Domain": _domain_of(r),
            "Address": r.get("street", ""),
            "Street": r.get("street", ""),
            "City": city,
            "State": state,
            "State/Region": state,
            "PostalCode": zipc,
            "Zip code": zipc,
            "Zip Code": zipc,
            "Country": r.get("country") or "",
            "Country/Region": r.get("country") or "",
            "Rating": r.get("ai_score") if r.get("ai_score") not in (None, "") else r.get("lead_score", ""),
            "Lead Status": r.get("list_status") or r.get("ai_verdict") or r.get("lead_grade", ""),
            "Industry": r.get("category", ""),
            "Lead Source": "Google Maps Extractor",
            "Description": _describe(r),
        }
        w.writerow(base)
    return buf.getvalue().encode("utf-8-sig")


def to_crm_csv(job_id: str, crm: str = "hubspot",
               q: str | None = None, filters: dict | None = None) -> bytes:
    """Export results remapped to a CRM's import-template column names."""
    return _rows_to_crm_csv(get_rows(job_id, q, filters), crm=crm)


def get_shortlist_rows(list_id: str) -> list[dict]:
    sl = db.get_saved_list(list_id)
    if not sl:
        return []
    rows = []
    for item in sl.get("items") or []:
        snap = _parse_json_val(item.get("snapshot_json"))
        merged = dict(snap) if isinstance(snap, dict) else {}
        for k, v in item.items():
            if k == "snapshot_json":
                continue
            if v not in (None, "") or k not in merged:
                merged[k] = v
        merged["list_status"] = item.get("status") or "New"
        merged["list_notes"] = item.get("notes") or ""
        rows.append(_enrich_row(merged))
    return rows


def export_shortlist(list_id: str, fmt: str = "csv", crm: str | None = None) -> bytes:
    rows = get_shortlist_rows(list_id)
    if crm:
        return _rows_to_crm_csv(rows, crm=crm)
    f = (fmt or "csv").lower()
    if f == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    if f == "xlsx":
        return _rows_to_xlsx(rows, columns=SHORTLIST_COLUMNS, title="Shortlist")
    return _rows_to_csv(rows, columns=SHORTLIST_COLUMNS)
