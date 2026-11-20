# Unauthenticated Google Maps Search — Format & Parser (2026-07-07)

Source capture: `un-auntheticated-request.xml` (34 MB BurpSuite export).

## Headline findings
- **No login required.** The captured session used only *visitor* cookies
  (`AEC=...; SOCS=...; __Secure-ENID=...`) — no `SID` / `__Secure-1PSID`.
  `tbm=map` search returns the full structured business array to anonymous
  and visitor sessions alike. Earlier "you must be signed in" assumption was
  WRONG.
- The old `requests` capture (logged-in, `gl=us`) is now stale in *format*:
  Google drifted the response layout. The unauthenticated capture shows the
  **current** layout, which the parser now targets.
- The modern result "card" already carries the *full* record (name, CID,
  coords, rating, reviews, category, address, phone, timezone, place_id), so
  the details step is now supplementary rather than mandatory.

## Response envelope
Depending on the exact `pb` used, the response is either:
- a plain JSON array: `)]}'\n[ ... ]`  (what our `pb.SEARCH_PB` returns), or
- a wrapped object: `{"c":0,"d":"...)]\n[[...]]", "e":"...", "p":..., "u":"..."}`
  where the real array is the JSON **string** in `d` (strip its own `)]}'\n`).

Either way, after unwrapping we get an array of length **72**. Business cards
live in **`arr[64]`** — a list of result *groups*; each group holds one card.
(The first/featured result is nested one level deeper, e.g. `[64][0][5][15]`.)

## Business card layout (verified indices)
| idx | meaning |
|-----|---------|
| `[0]` | result token (e.g. `LvFMapbLO5GJ7NYP...`) |
| `[1]` | tracking token (`0ahUKEwi...`) |
| `[2]` | `[address, area]` e.g. `['80-57 Lefferts Boulevard', 'Kew Gardens, NY 11415']` |
| `[4]` | `[…, rating @7, reviews @8]` |
| `[9]` | `[null, null, lat, lng]` |
| `[10]` | **CID** as hex string `0x…:0x…` |
| `[11]` | **name** |
| `[13]` | `[category]` |
| `[18]` | full title |
| `[30]` | timezone (e.g. `America/New_York`) |
| `[39]` | full address |
| `[76]` | `[category tag]` |
| `[82]` | `[…, address, address]` |
| `[178]` | `[[formatted, None, None, E.164]]` → phone |
| `[203]` | opening hours |
| `[227]` | `[CID, None, None, kgmid, place_id('ChIJ…')]` |

Notes:
- Google wraps many string values in a single pair of quotes inside the JSON
  (e.g. `"'80-57 Lefferts Boulevard'"`). `fields._strip_quotes` removes one layer.
- Phone is extracted with a regex (`+1 917-300-6163` style) when present.
- `reviews_count` is present in the captured file (`card[4][8]`) but came back
  `None` on a live test — the live rating block may shift the reviews index.
  Rating itself is reliable.

## Ads
Not yet isolated in the new format (legacy was `arr[2][11][0]`). Organic is the
priority and is fully working; ads extraction can be added once a live ad
response is captured.

## Code changes
- `backend/scraper/search.py::parse_search_response` — rewritten: unwraps the
  envelope, collects cards from `arr[64]`, feeds each to `build_business`.
  Returns `(organic_rows, [])`; each row is `Business.to_row()`.
- `backend/scraper/fields.py::build_business` — already used the correct modern
  card indices; added `_strip_quotes` and `place_id` extraction from `[227][4]`.
- `backend/jobs.py` — search card data is now the **primary** record;
  `fetch_details` only *supplements* (website/phone/etc.). If details fails, the
  rich search data is kept, so extraction never loses results.
- `backend/scraper/details.py::fetch_details` — works as-is with the new hex CID
  (`0x…:0x…`); verified live (returns a `Business`).

## Verification
- Offline parse of `un-auntheticated-request.xml` (item 278, NYC-area search):
  **22 businesses** extracted with name/category/rating/reviews/phone/address/CID.
- Live anonymous `search("dry cleaner New York")` via `pb.SEARCH_PB`:
  **10 businesses** with name/rating/phone/address/CID.
- Live `fetch_details(<new CID>)` returns a `Business` (name + phone match).

## Caveats
- `reviews_count` may be `None` on live responses (index shift) — minor.
- `website` is often absent from the search card; details sometimes has it.
- Ads not extracted yet in the new format.
- Response format still varies slightly between requests (envelope/featured
  nesting); the parser tolerates this via the `arr[64]` + whole-doc fallback.
