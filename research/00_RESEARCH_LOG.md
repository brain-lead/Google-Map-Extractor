# Google Maps Extraction — Research Log (LIVING DOCUMENT)

> This file is written **as I learn**, not after. Each section records what I
> observed in the captured BurpSuite traffic (`requests`, 577 items, 34 MB),
> what worked, what didn't, and the plan to replicate it with `curl_cffi`.
>
> Capture context: browser = Firefox 120 / Windows; Google session **logged in**
> (cookies present). Locale seen in traffic: `hl=en`, `gl=ng` (session set to
> Nigeria). Searches performed: `plumber in new york`, `school`, `ball in …`.

---

## 2026-07-07 — Session 1: Parsing the capture & finding the real endpoints

### What I did
1. Built `research/parse_index.py` — streams the 34 MB Burp XML with
   `iterparse`, writes `research/01_index/index.csv` + `.json` (url, method,
   status, mimetype, sizes) without loading it all into RAM.
2. Filtered the 577 items for Maps traffic. Found the real data endpoints
   among hundreds of JS/CSS/vector-tile noise.

### Key finding — the 4 endpoints that matter
| # | Endpoint | Purpose | Sample item |
|---|----------|---------|-------------|
| 1 | `GET /search?tbm=map&q=<Q>&pb=...` | **Search → list of businesses** | 103, 226, 276, 302, 315, 322, 344, 466, 487 |
| 2 | `GET /maps/preview/place?pb=!1m14!1s<CID>...` | **Full business record** | 269, 335, 420 |
| 3 | `GET /s?tbm=map&gs_ri=maps&suggest=p&q=<Q>&pb=...` | **Autocomplete / suggestions** | 337–343, 423–465 |
| 4 | `POST /maps/_/MapsWizUi/data/batchexecute?rpcids=...` | UI side-data (related/ads) | 104, 112, 113, 117, 194, 374, 447 |

Everything else (`/maps/vt/...`, `/maps/_/js/...`, `/xjs/...`, `gen_204`) is
map tiles, scripts, or telemetry — **ignore for scraping**.

---

## 2026-07-07 — Endpoint 1: SEARCH (`tbm=map`)

### Request shape (item 103)
```
GET /search?tbm=map&authuser=0&hl=en&gl=ng&q=plumber+in+new+york&pb=<ENCODED> HTTP/2
Host: www.google.com
Cookie: <full logged-in session: SID, __Secure-1PSID, __Secure-3PSID, HSID,
        SSID, APISID, SAPISID, NID, __Secure-1PSIDTS, ...>
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) ... Firefox/120.0
Accept: */*
Referer: https://www.google.com/maps/search/plumber+in+new+york
Sec-Fetch-Dest: empty / Mode: cors / Site: same-origin
```
**Critical:** the request is authenticated by the session **cookies**. No API
key. Without valid cookies → consent redirect or blocked/empty body.

### Response shape
- Content-Type: `application/json`. Body has an XSSI prefix `)]}'\n`, then a
  JSON **array**. Strip the prefix, then `json.loads`.
- Top level `j` is a list. Structure observed:
  - `j[0]` = query string (`"plumber in new york"`)
  - `j[1]` = viewport metadata (bounds etc.)
  - `j[2][11][0][i]` = **ADS** (Google Local Services Ads)
  - `j[16][3][0][4][i]` = **ORGANIC** results

### AD entry (`j[2][11][0][i]`) — rich but sponsored
```
[ '0x89c2ec9cd3075c3b:0x33b66248f14d31f0',   # CID (hex)
  'AJ plumbing',                              # name
  [ [.., .., lat, lng],                       # coords
    null, null,
    ['4.4★ (19) · Professional Gas Plumbing'],# rating+review string
    null, 1, 4.4 ],                            # 4.4 = rating float
  [ ..., 'www.ajplumbingonline.com/', ... ],  # website
  [ 'https://www.google.com/aclk?...', ... ], # ← ad marker (aclk)
  [ 'ajplumbingonline.com', 'This ad was shown...', 0, [...] ],
  [16383, 0, null, null, [177,93,1469,179,248], 0, 1],
  null, '...' ]
```
- Ad detection: presence of `aclk` / `adview` / `"This ad was shown"`.

### ORGANIC entry (`j[16][3][0][4][i]`) — sparse summary
```
[ ['9926770384415897943', '13676938414854398931'],  # DECIMAL CID components
  '/g/11vwqy0dcp',                                  # Knowledge-Graph GID
  [ [ts, 0,0,0, null, '/aclk?...'],                 # (sometimes ad-tagged)
    [null, null, 40.884883, -74.076735],            # [?, ?, lat, lng]
    'ADU Water Fire Mold Storm' ],                  # name
  [408848830, 3554199946],
  null, null, ... ]
```
- **Important gotcha:** organic entries in the search response carry ONLY
  name + coordinates + the two **decimal** CID numbers + a GID. They do **NOT**
  contain rating, phone, website, address, or hours. Those come from the
  **place-details** endpoint (Endpoint 2) — so a 2-step scrape is required for
  full business data.
- The 21 organic entries observed here were name + coords only.

### CID conversion (needed to call Endpoint 2)
- Ads give the CID directly as hex: `0x89c2ec9cd3075c3b:0x33b66248f14d31f0`.
- Organic gives decimal pair `[id1, id2]`. Convert:
  ```python
  cid = f"0x{int(id1):x}:0x{int(id2):x}"
  ```
  Verified: organic pair `['9926770384415897943','13676938414854398931']`
  → `0x89c2f91201fa3957:0xbdce3f06584a63d3` (first half matches the `0x89c2…`
  prefix all real CIDs share). **Hypothesis, to be validated by a live
  details call in the build phase.**

---

## 2026-07-07 — Endpoint 2: PLACE DETAILS (`/maps/preview/place`)

### Request shape (item 269)
```
GET /maps/preview/place?authuser=0&hl=en&gl=ng&pb=!1m14!1s<CID>&3m9!... HTTP/2
```
- The place is identified by its **hex CID** passed as `!1s<CID>` in the `pb`
  param (URL-encoded, e.g. `0x89c2f6643d4d2a5d%3A0xb9b1b402abaab920`).
- Same session cookies + Referer/`Sec-Fetch-*` headers as Endpoint 1.

### Response shape (item 269 — "24/7 Manhattan Plumbing NYC")
XSSI prefix `)]}'\n` + JSON array; the business record is at **`j[6]`**:
| Path | Meaning | Example |
|------|---------|---------|
| `j[6][2][0]` | street address | `3441 Broadway` |
| `j[6][2][1]` | city/state/zip | `New York, NY 10031` |
| `j[6][4][7]` | **rating** (float) | `4.4` |
| `j[6][4][8]` | **review count** | `56` |
| `j[6][4][3][0]` | reviews URL (has `place_id`) | `https://search.google.com/local/reviews?placeid=ChIJ…` |
| `j[6][7][0]` | website URL | `https://247manhattanplumbingnyc.com/?GMB=webclick` |
| `j[6][7][1]` | website domain | `247manhattanplumbingnyc.com` |
| `j[6][9]` | `[_, _, lat, lng]` | `[null,null,40.8236159,-73.9529142]` |
| `j[6][10]` | CID (hex) | `0x89c2f6643d4d2a5d:0xb9b1b402abaab920` |
| `j[6][11]` | **name** | `24/7 Manhattan Plumbing NYC` |
| `j[6][13]` | categories | `["Plumber"]` |
| `j[6][18]` | full title string | `24/7 Manhattan Plumbing NYC, 3441 Broadway, …` |
| `j[6][30]` | timezone | `America/New_York` |
| `j[6][31]` | **reviews** (author, text, photos, id) | list |
| `j[6][39]` | formatted address | `3441 Broadway, New York, NY 10031, United States` |
| `j[6][42]` | maps preview URL | `https://www.google.com/maps/preview/place/…` |
| `j[6][51]` | **photos** (image URLs) | list |

- **Phone:** NOT present in this sample. In other Google formats phone lives
  near `j[6][13]`; here `j[6][13]` is categories, so for this business Google
  simply didn't expose a phone. Plan: when building, scan `j[6]` for
  `+1…` / `(\d{3})` patterns rather than assuming a fixed index.
- This endpoint is the **rich data source** — fire it once per result CID.

---

## 2026-07-07 — Endpoint 3: AUTOCOMPLETE (`/s?tbm=map&suggest=p`)

### Request (item 337)
```
GET /s?tbm=map&gs_ri=maps&suggest=p&authuser=0&hl=en&gl=ng
    &psi=<token>.<ts>&q=<Q>&ech=1&pb=!2i6!4m9!...
```
### Response
JSON array (XSSI prefix present). `j[0]` = query; `j[0][1][-1]` holds the
suggestion list `[["plumber in new york", ...], ...]`. Useful for an
autocomplete box in the UI, not needed for batch extraction.

---

## 2026-07-07 — Endpoint 4: batchexecute (MapsWizUi)

`POST /maps/_/MapsWizUi/data/batchexecute?rpcids=<EvxQ3b|Qt4aBe|T4jwAf|r4skrb>`
with `source-path` = the current maps URL. Returns small JSON side-data
(related places, ad info). **Low priority** — the 3 endpoints above cover
search → details → suggest. Will revisit only if details are incomplete.

---

## What WORKED / what DIDN'T (so far)

**Worked**
- Stripping the `)]}'\n` XSSI prefix then `json.loads` → clean parse.
- Locating the result arrays (`j[2][11][0]` ads, `j[16][3][0][4]` organic).
- Locating the full record at `j[6]` of the details response.
- Reconstructing the hex CID from the organic decimal pair.

**Didn't / caveats**
- Organic search rows are thin (no rating/phone/site). Must call details per
  CID → 2-step scrape, N+1 requests. Rate-limit / ban risk → pace it.
- `gl=ng` geolocates results to Nigeria; the capture's queries included the
  city so results were correct, but a bare query without a location will be
  Nigeria-centered. Fix: always include location in query, or set `gl`/`hl` to
  target market.
- CID decimal→hex mapping is a hypothesis (not yet validated with a live
  details call).
- Phone index not confirmed; treat as pattern-search, not fixed offset.
- The `pb` request param is a custom `!`-delimited encoding. We do **not** need
  to generate it from scratch — we can **reuse a captured `pb` verbatim** and
  only swap the query/CID tokens. This is the pragmatic path.

---

## 2026-07-07 — LIVE validation (curl_cffi 0.15.0)
Replayed the **SEARCH** endpoint with `curl_cffi` (`impersonate="chrome120"`),
reusing the captured `pb` + captured cookies, ~37 min after capture.

- `status 200`, but body was only **5,265 bytes** (capture was 313,896).
- Returned a minimal `["plumber in new york",[...]]` shell — same *shape* as
  the real response (`j[0]`=query, `j[1]`=metadata) but **empty result
  arrays** (`j[16][3][0][4]` absent → `IndexError`).
- **Conclusion:** the endpoint is correct and the decode logic is correct
  (it parses the real captured 313 KB sample perfectly). The failure is
  **stale auth**: `__Secure-1PSIDTS` and friends are short-lived, so a live
  scrape must use **fresh cookies** (login shortly before, or refresh).
  The saved `requests` capture remains the authoritative sample of the real
  format; treat its cookies as expired for live use.

### Updated "what didn't work"
- **Replaying with old cookies → truncated/empty results.** Must obtain fresh
  session cookies at scrape time (this is the #1 gotcha for production).

---

## Next: the replication plan → see `06_findings/REPLICATION_PLAN.md`
