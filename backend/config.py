"""Configuration & paths for the Google Maps Business Extractor backend."""
import os
import sys
import base64
from pathlib import Path
from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent.parent          # google-map-extractor/
BACKEND_DIR = Path(__file__).resolve().parent              # backend/

# When bundled as a Nuitka or PyInstaller EXE, user-writable data goes to
# per-user AppData on Windows (%APPDATA%\BrainLead\data), while read-only assets
# are resolved from either the binary bundle or the persistent application root.
if getattr(sys, "frozen", False) or "__compiled__" in globals() or hasattr(sys, "nuitka_version"):
    _DATA_BASE = Path(os.environ.get("APPDATA", Path.home())) / "BrainLead"
else:
    _DATA_BASE = BACKEND_DIR
DATA_DIR = _DATA_BASE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _resolve_frontend_dist() -> Path:
    candidates = [
        BASE_DIR / "frontend" / "dist",
        Path(sys.argv[0]).resolve().parent / "frontend" / "dist",
        Path(sys.executable).resolve().parent / "frontend" / "dist",
        Path(__file__).resolve().parent.parent / "frontend" / "dist",
    ]
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return BASE_DIR / "frontend" / "dist"

FRONTEND_DIST = _resolve_frontend_dist()
DB_PATH = DATA_DIR / "app.db"
COOKIES_FILE = DATA_DIR / "cookies.enc"
KEY_FILE = DATA_DIR / "secret.key"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Default market (Google geo/locale). Override per-job.
DEFAULT_GL = "us"
DEFAULT_HL = "en"

# curl_cffi browser impersonation
IMPERSONATE = "chrome120"

# Concurrency for details enrichment
DETAILS_CONCURRENCY = 4
# Default "threads" setting (configurable per-user in the UI). Controls how many
# tile searches run concurrently AND how many businesses are enriched at once.
# Each concurrent Google call rotates through the proxy pool.
DEFAULT_THREADS = 2
# Concurrency for the website crawl (enrich_website). This hits each business's
# OWN third-party site, NOT Google, so it is not bound by Google's rate limit
# and can run many parallel threads.
WEB_CONCURRENCY = 16
REQUEST_JITTER = (0.5, 1.8)   # seconds between details calls

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def base_headers(referer: str = "https://www.google.com/maps") -> dict:
    h = dict(_HEADERS)
    h["Referer"] = referer
    return h


def get_fernet() -> Fernet:
    if KEY_FILE.exists():
        key = KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
    return Fernet(key)


def encrypt_bytes(data: bytes) -> bytes:
    return get_fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return get_fernet().decrypt(data)
