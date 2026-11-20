"""Global country -> Google market (gl/hl) mapping and helpers.

This is what makes the tool "smart" about where to search: given a drawn
area, a typed location, or an explicit country the user picked, we resolve the
correct Google `gl` (geo/market) and `hl` (interface language) so a
non-technical user never has to know what those mean.

`gl` is the ISO 3166-1 alpha-2 country code (lowercased) — the value Google's
search endpoint expects for its market. `hl` defaults to `en-<CC>`; a few
markets override it with the local language for better native results.
"""

from pycountry import countries as _PYCOUNTRIES

# Markets where returning Google's UI/results in the local language is clearly
# better than English. Everything else defaults to en-<CC>.
_LOCAL_HL = {
    "FR": "fr-FR", "DE": "de-DE", "ES": "es-ES", "PT": "pt-PT", "BR": "pt-BR",
    "IT": "it-IT", "NL": "nl-NL", "RU": "ru-RU", "JP": "ja-JP", "KR": "ko-KR",
    "CN": "zh-CN", "TW": "zh-TW", "SA": "ar-SA", "MX": "es-MX", "AR": "es-AR",
}

# Common name variants / abbreviations -> canonical ISO alpha-2 code.
_ALIASES = {
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "great britain": "GB",
    "united kingdom": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "britain": "GB",
    "united kingdom of great britain and northern ireland": "GB",
    "u.a.e.": "AE", "united arab emirates": "AE", "emirates": "AE",
    "russia": "RU", "russian federation": "RU",
    "south korea": "KR", "republic of korea": "KR",
    "north korea": "KP", "dprk": "KP",
    "turkey": "TR", "turkiye": "TR",
    "iran": "IR", "islamic republic of iran": "IR",
    "vietnam": "VN", "viet nam": "VN",
    "czech republic": "CZ", "czechia": "CZ",
    "ivory coast": "CI", "côte d'ivoire": "CI",
    "cape verde": "CV", "cabo verde": "CV",
    "swaziland": "SZ", "eswatini": "SZ",
    "burma": "MM", "myanmar": "MM",
    "moldova": "MD", "republic of moldova": "MD",
    "macau": "MO", "macao": "MO",
    "hong kong": "HK",
    "taiwan": "TW",
    "south sudan": "SS",
    "laos": "LA", "lao people's democratic republic": "LA",
    "syria": "SY", "syrian arab republic": "SY",
    "bolivia": "BO", "bolivia (plurinational state of)": "BO",
    "venezuela": "VE", "venezuela (bolivarian republic of)": "VE",
    "tanzania": "TZ", "united republic of tanzania": "TZ",
    "kosovo": "XK",
}

# Build the canonical country table once at import.
COUNTRIES = []
_NAME_INDEX = {}  # lowercased name -> entry
for _c in _PYCOUNTRIES:
    _code = _c.alpha_2
    _name = _c.name
    _entry = {
        "code": _code,
        "name": _name,
        "gl": _code.lower(),
        "hl": _LOCAL_HL.get(_code, "en-" + _code),
    }
    COUNTRIES.append(_entry)
    _NAME_INDEX[_name.lower()] = _entry


def normalize_country(token: str | None) -> str | None:
    """Resolve a country name or code (case-insensitive) to its ISO alpha-2
    code, or None if it can't be matched."""
    if not token:
        return None
    tl = token.strip().lower()
    if not tl:
        return None
    if tl in _ALIASES:
        return _ALIASES[tl]
    if tl in _NAME_INDEX:
        return _NAME_INDEX[tl]["code"]
    for entry in COUNTRIES:
        if entry["code"].lower() == tl:
            return entry["code"]
    for entry in COUNTRIES:
        if entry["name"].lower() == tl:
            return entry["code"]
    # "City, Country" style strings: the last segment is usually the country.
    if "," in tl:
        for part in reversed([p.strip() for p in tl.split(",")]):
            if not part:
                continue
            if part in _ALIASES:
                return _ALIASES[part]
            if part in _NAME_INDEX:
                return _NAME_INDEX[part]["code"]
            for entry in COUNTRIES:
                if entry["code"].lower() == part:
                    return entry["code"]
            for entry in COUNTRIES:
                if entry["name"].lower() == part:
                    return entry["code"]
    return None


def gl_for_country(token: str | None) -> str | None:
    code = normalize_country(token)
    return code.lower() if code else None


def hl_for_country(token: str | None) -> str | None:
    code = normalize_country(token)
    if not code:
        return None
    return _LOCAL_HL.get(code, "en-" + code)


def list_countries() -> list:
    """All countries as {code, name, gl, hl} for the UI dropdown."""
    return [
        {"code": e["code"], "name": e["name"], "gl": e["gl"], "hl": e["hl"]}
        for e in sorted(COUNTRIES, key=lambda x: x["name"])
    ]
