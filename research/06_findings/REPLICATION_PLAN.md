# Replication Plan — Google Maps Business Extractor (curl_cffi)

Goal: reproduce what the captured browser traffic does, in Python, so we can
scrape business data at scale behind a professional UI.

## 0. Hard requirements (learned from capture)
1. **Authenticated session cookies.** The `tbm=map` and `preview/place`
   endpoints are gated by a logged-in Google session. No API key. We must
   persist cookies from a real login (the Burp capture already has them in
   `research/02_endpoints/0103/request.txt` — reuse for experiments, then
   supply your own for production).
2. **HTTP/2 + browser impersonation.** `curl_cffi` with
   `impersonate="chrome120"` (or firefox). Send the captured `User-Agent`,
   `Accept`, `Referer`, and `Sec-Fetch-*` headers — they are checked.
3. **Geo/locale.** Set `hl=en` and choose `gl` to match the target market
   (capture used `gl=ng`; for US results use `gl=us` **and** put the city in
   the query). A bare query with `gl=ng` returns Nigeria businesses.

## 1. Search step (list of businesses)
```
GET https://www.google.com/search
    ?tbm=map&authuser=0&hl=en&gl=<market>
    &q=<urlencoded "plumber in new york">
    &pb=<REUSED captured pb from item 103, query token swapped>
```
- Reuse the captured `pb` verbatim (don't try to generate it). The query also
  lives in `q=`, which is what Google actually uses for the result set.
- Parse: strip `)]}'\n`, `json.loads`, then:
  - ads   = `j[2][11][0]`            (filter out via `aclk`/`adview` markers)
  - organic = `j[16][3][0][4]`       (primary source)
- For each organic row `p`:
  ```python
  id1, id2 = p[0]                       # decimal CID pair
  name     = p[2][2]                    # name
  lat, lng = p[2][1][2], p[2][1][3]     # coordinates
  cid      = f"0x{int(id1):x}:0x{int(id2):x}"   # for details call
  gid      = p[1]                       # '/g/...' knowledge id
  ```
- Optional: also harvest ads (`j[2][11][0]`) which already carry rating +
  website, if sponsored coverage is acceptable.

## 2. Details step (full record) — per CID
```
GET https://www.google.com/maps/preview/place
    ?authuser=0&hl=en&gl=<market>
    &pb=!1m14!1s<urlencoded cid>!3m9!...   # reuse captured pb from item 269
```
- Replace only the `!1s<CID>` token with the target hex CID.
- Parse: strip `)]}'\n`, `j[6]` is the record. Map fields per the table in
  `00_RESEARCH_LOG.md` (name `j[6][11]`, address `j[6][2]`, rating
  `j[6][4][7]`, reviews `j[6][4][8]`, website `j[6][7]`, coords `j[6][9]`,
  categories `j[6][13]`, reviews `j[6][31]`, photos `j[6][51]`).
- **Phone:** scan `j[6]` for `\+?1?[\s.-]?\(?\d{3}\)?...` — do NOT assume a
  fixed index (absent in the sampled business).

## 3. Autocomplete (UI nicety)
```
GET https://www.google.com/s?tbm=map&gs_ri=maps&suggest=p
    &q=<partial>&pb=<reused captured pb from item 337>
```
Suggestions at `j[0][1][-1]`.

## 4. Robustness / anti-ban
- Reuse one `curl_cffi` `Session` (keeps cookies + HTTP/2 + JA3 stable).
- **Pace** details calls: a few per second, random jitter, between searches.
- Rotate/refresh cookies when you see a consent redirect or empty `j`.
- Keep `User-Agent` + `Sec-Fetch-*` headers consistent with the impersonation.
- Handle pagination: the `pb` param carries result count/page tokens
  (`!7i20` etc.); for >20 results, iterate the `pb` (or simply re-issue search
  with incremented token) — confirm during build.

## 5. Open validations (do in build phase, not research)
- [ ] Fire a live details call using the decimal→hex CID conversion; confirm
      `j[6]` matches.
- [ ] Confirm whether organic rows can carry rating inline (some layouts do);
      if yes, skip details for those.
- [ ] Confirm phone index/pattern across several businesses.
- [ ] Confirm `gl`/`hl` switching changes result geo-center as expected.
- [ ] Confirm reused `pb` keeps working after cookies refresh, or pin a known-
      good minimal `pb`.
