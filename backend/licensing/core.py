"""
Brain Lead licensing core for GME (Google Map Extractor).

Follows the official brainlead-auth specification (https://brainlead.dev):
  - deterministic machine HWID retrieval (Windows 10/11-safe)
  - 3-attempt retry with SSL certificate fallback
  - XOR + Base64 encrypted license persistence with multi-key decryption
  - self-service hardware binding reset via /reset-license-binding-user
  - broadcast notification polling via /get-notifications-v2
  - free-tier fallback & branding metadata
"""
import base64
import datetime
import getpass
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path
import requests

from backend.licensing.app_info import (
    ADD_TODAY_DATE,
    ADMIN_NOTIFICATION_KEY,
    APP_DISPLAY_NAME,
    APP_ID,
    APP_NAME,
    APP_VERSION,
    BUILD_DATE,
    BUY_LICENSE_URL,
    CAMPAIGN_USERNAME,
    DEFAULT_USERNAME,
    DEVELOPER,
    DEVELOPER_BOT,
    DEVELOPER_CONTACT,
    DEVELOPER_TELEGRAM,
    FREE_AREA_SCAN_MAX_TILES,
    FREE_MAX_RESULTS_PER_SEARCH,
    LICENSE_PREFIX,
    RELEASE_TYPE,
    TELEGRAM_BOT_URL,
    WEBSITE_URL,
    get_backend_config,
    notink,
)
from backend.config import BASE_DIR, DATA_DIR

# Primary key follows official Brain Lead AGENTS.md and brainlead-auth standard.
ENCRYPTION_KEYS = [
    "brainlead_decrytion_secure_key_v1",
    "brianlead_decrytion_secure_key_v1",
    "brainlead_decrytion_secure_key1",
    "brainleadbot_decrytion_secure_key_v1",
]
PRIMARY_ENCRYPTION_KEY = ENCRYPTION_KEYS[0]


# --------------------------- XOR "encryption" ---------------------------
def encrypt_text(text, key=PRIMARY_ENCRYPTION_KEY):
    """Simple XOR encryption with base64 encoding."""
    result = "".join(chr(ord(char) ^ ord(key[i % len(key)])) for i, char in enumerate(text))
    return base64.b64encode(result.encode("latin1")).decode("ascii")


def decrypt_text(encrypted_text, key=None):
    """Simple XOR decryption with multi-key fallback for legacy license files."""
    if not encrypted_text:
        return None
    keys = [key] if key else ENCRYPTION_KEYS
    for k in keys:
        try:
            decoded = base64.b64decode(encrypted_text.encode("ascii")).decode("latin1")
            result = "".join(chr(ord(char) ^ ord(k[i % len(k)])) for i, char in enumerate(decoded))
            if result and all(32 <= ord(c) <= 126 for c in result) and any(c.isalnum() for c in result):
                return result
        except Exception:
            continue
    return None


# ------------------------------ HWID -----------------------------------
_CACHED_HWID = None
_PLACEHOLDER_UUIDS = {
    "",
    "UUID",
    "NONE",
    "TO BE FILLED BY O.E.M.",
    "00000000-0000-0000-0000-000000000000",
    "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
}


def get_system_hwid():
    """Deterministic hardware identifier (WMIC -> CIM -> Registry -> static host hash)."""
    global _CACHED_HWID
    if _CACHED_HWID:
        return _CACHED_HWID

    def _valid_uid(val):
        v = str(val or "").strip()
        if not v or len(v) < 8 or v.upper() in _PLACEHOLDER_UUIDS:
            return None
        return v

    if platform.system() == "Windows":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for cmd in (
            ["wmic", "csproduct", "get", "UUID"],
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"],
        ):
            try:
                out = subprocess.check_output(
                    cmd, stderr=subprocess.DEVNULL, creationflags=creationflags, timeout=4
                ).decode("utf-8", errors="ignore")
                for line in out.splitlines():
                    cand = _valid_uid(line)
                    if cand:
                        _CACHED_HWID = cand
                        return cand
            except Exception:
                pass
        try:
            import winreg

            for reg_path, val_name in (
                (r"SOFTWARE\Microsoft\Cryptography", "MachineGuid"),
                (r"SOFTWARE\Microsoft\SQMClient", "MachineId"),
            ):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as k:
                        guid, _ = winreg.QueryValueEx(k, val_name)
                        cand = _valid_uid(str(guid).strip("{} "))
                        if cand:
                            _CACHED_HWID = cand
                            return cand
                except Exception:
                    continue
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            with open("/etc/machine-id", "r", encoding="utf-8") as f:
                cand = _valid_uid(f.read())
                if cand:
                    _CACHED_HWID = cand
                    return cand
        except Exception:
            pass

    static_seed = (
        f"{os.environ.get('COMPUTERNAME', '')}-"
        f"{os.environ.get('PROCESSOR_IDENTIFIER', '')}-"
        f"{get_computer_username()}"
    )
    _CACHED_HWID = hashlib.sha256(static_seed.encode("utf-8", errors="ignore")).hexdigest()[:32].upper()
    return _CACHED_HWID


def get_computer_username():
    try:
        u = getpass.getuser()
        if u and not u.startswith("web_"):
            return u
    except Exception:
        pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


# -------------------------- License storage ---------------------------
# Support Nuitka onefile (__compiled__ using sys.argv[0]), PyInstaller, and dev mode.
if "__compiled__" in globals() or getattr(sys, "frozen", False):
    _EXEC_DIR = Path(os.path.dirname(os.path.abspath(sys.argv[0])))
else:
    _EXEC_DIR = BASE_DIR

LICENSE_DIR = DATA_DIR / "licensing"
LICENSE_FILE = LICENSE_DIR / "license_data.json"
LEGACY_LICENSE_FILES = [
    _EXEC_DIR / "database" / "license_data.json",
    BASE_DIR / "database" / "license_data.json",
]


def _valid_license_pair(license_key: str | None, username: str | None) -> bool:
    if not license_key or not username:
        return False
    if not all(c.isalnum() or c in "-_" for c in license_key):
        return False
    if not all(c.isalnum() or c in "-_.@" for c in username):
        return False
    return len(license_key) >= 4 and len(username) >= 4


def _candidate_license_files():
    return [LICENSE_FILE, *LEGACY_LICENSE_FILES]


def load_saved_license():
    """Load saved license from disk with decryption -> (key, username)."""
    for path in _candidate_license_files():
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            encrypted_key = str(data.get("license_key") or "").strip()
            encrypted_username = str(data.get("username") or "").strip()
            if not encrypted_key:
                continue
            for k in ENCRYPTION_KEYS:
                license_key = decrypt_text(encrypted_key, key=k)
                username = decrypt_text(encrypted_username, key=k) if encrypted_username else None
                if license_key and not username and _valid_license_pair(license_key, f"{LICENSE_PREFIX}_{license_key}"):
                    username = f"{LICENSE_PREFIX}_{license_key}"
                if _valid_license_pair(license_key, username):
                    return license_key, username
            # Plaintext backwards compatibility -> migrate to encrypted format
            if _valid_license_pair(encrypted_key, encrypted_username or f"{LICENSE_PREFIX}_{encrypted_key}"):
                user = encrypted_username or f"{LICENSE_PREFIX}_{encrypted_key}"
                save_license(encrypted_key, user)
                return encrypted_key, user
        except Exception:
            continue
    return None, None


def save_license(license_key, username):
    """Save license to file with encryption."""
    try:
        LICENSE_DIR.mkdir(parents=True, exist_ok=True)
        encrypted_key = encrypt_text(license_key.strip())
        encrypted_username = encrypt_text(username.strip())
        data = {
            "license_key": encrypted_key,
            "username": encrypted_username,
            "saved_date": str(uuid.uuid4()),
        }
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def clear_saved_license():
    """Remove stored license files."""
    removed = False
    for path in _candidate_license_files():
        try:
            if path.exists():
                path.unlink()
                removed = True
        except Exception:
            pass
    _AUTH_CACHE["status"] = None
    return removed


# --------------------------- HTTP Helpers ------------------------------
def _post_with_retry(url, json_payload, timeout=15, retries=3):
    """POST JSON with retry and SSL verification fallback for older Windows stores."""
    last_err = None
    for attempt in range(retries):
        try:
            try:
                return requests.post(url, json=json_payload, timeout=timeout)
            except requests.exceptions.SSLError:
                return requests.post(url, json=json_payload, timeout=timeout, verify=False)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(0.4 * (attempt + 1))
    raise last_err


def _get_with_retry(url, timeout=10, retries=2):
    last_err = None
    for attempt in range(retries):
        try:
            try:
                return requests.get(url, timeout=timeout)
            except requests.exceptions.SSLError:
                return requests.get(url, timeout=timeout, verify=False)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(0.3)
    raise last_err


# --------------------------- Authorization -----------------------------
backend_config = get_backend_config()
HWID_API_URL = backend_config["hwid_endpoint"]
RESET_BINDING_API_URL = backend_config["reset_binding_endpoint"]
NOTIFICATION_API_URL = backend_config["notification_endpoint"]

_AUTH_CACHE = {"status": None, "ts": 0, "ttl": 30}
_NOTIF_CACHE = {"data": None, "ts": 0, "ttl": 300}


def is_campaign_username(username=None):
    """Check if the supplied/username is the fixed campaign username."""
    check = username if username is not None else DEFAULT_USERNAME
    return bool(check and check == CAMPAIGN_USERNAME)


def is_binding_conflict(message: str | None) -> bool:
    """True when the server reports the license is already bound to another device."""
    low = (message or "").lower()
    return any(tok in low for tok in ("already bound", "already being used", "device limit"))


def _post_hwid(username):
    today_str = datetime.date.today().isoformat() if ADD_TODAY_DATE else BUILD_DATE
    payload = {
        "username": username,
        "hwid": get_system_hwid(),
        "computer_username": get_computer_username(),
        "app_version": APP_VERSION,
        "build_date": BUILD_DATE,
        "today_date": today_str,
        "add_today_date": ADD_TODAY_DATE,
        "release_type": RELEASE_TYPE,
        "developer": DEVELOPER,
        "app_name": APP_NAME,
        "app_id": APP_ID,
    }
    return _post_with_retry(HWID_API_URL, payload, timeout=15, retries=3)


def check_authorization(force=False):
    """Return a structured status dict. Cached for `ttl` seconds."""
    now = time.time()
    if not force and _AUTH_CACHE["status"] and (now - _AUTH_CACHE["ts"]) < _AUTH_CACHE["ttl"]:
        return _AUTH_CACHE["status"]

    saved_license, saved_username = load_saved_license()
    username = saved_username or (f"{LICENSE_PREFIX}_{saved_license}" if saved_license else DEFAULT_USERNAME)

    try:
        response = _post_hwid(username)
        result = response.json() if response.content else {}
        if response.status_code == 200:
            status = {
                "status": "authorized",
                "plan": "licensed" if saved_license else "free",
                "limited": not bool(saved_license),
                "has_saved_license": bool(saved_license),
                "binding_conflict": False,
                "username": username,
                "message": result.get("message", "Authorized"),
            }
        else:
            error_msg = result.get("message") or result.get("error") or "Authorization failed"
            status = {
                "status": "unauthorized",
                "plan": None,
                "limited": True,
                "has_saved_license": bool(saved_license),
                "binding_conflict": is_binding_conflict(error_msg),
                "username": username,
                "message": error_msg,
            }
    except Exception:
        if saved_license:
            status = {
                "status": "authorized",
                "plan": "licensed",
                "limited": False,
                "has_saved_license": True,
                "binding_conflict": False,
                "username": username,
                "offline": True,
                "message": "Offline (cached license)",
            }
        else:
            status = {
                "status": "unreachable",
                "plan": None,
                "limited": True,
                "has_saved_license": False,
                "binding_conflict": False,
                "username": username,
                "message": (
                    "Could not reach the license server. Check your connection and retry, or enter a license key."
                ),
            }

    _AUTH_CACHE["status"] = status
    _AUTH_CACHE["ts"] = now
    return status


def is_limited():
    """True when the current user is on the free (limited) tier."""
    return bool(check_authorization().get("limited"))


def activate(license_key):
    """Validate and store a license key. Returns a status dict."""
    key = (license_key or "").strip().upper()
    if not key:
        return {
            "status": "unauthorized",
            "plan": None,
            "limited": True,
            "binding_conflict": False,
            "message": "Please enter a valid license key.",
        }
    username = f"{LICENSE_PREFIX}_{key}"
    try:
        response = _post_hwid(username)
        result = response.json() if response.content else {}
        if response.status_code == 200:
            save_license(key, username)
            _AUTH_CACHE["status"] = None
            return {
                "status": "authorized",
                "plan": "licensed",
                "limited": False,
                "has_saved_license": True,
                "binding_conflict": False,
                "username": username,
                "message": result.get("message", "License activated successfully"),
            }
        msg = result.get("message") or result.get("error") or "Invalid license key"
        return {
            "status": "unauthorized",
            "plan": None,
            "limited": True,
            "binding_conflict": is_binding_conflict(msg),
            "message": msg,
        }
    except Exception as e:
        return {
            "status": "unreachable",
            "plan": None,
            "limited": True,
            "binding_conflict": False,
            "message": f"Could not verify key: {e}",
        }


def reset_binding(license_key=""):
    """Self-service reset of hardware binding, then re-activate on this PC."""
    key = (license_key or "").strip().upper()
    saved_key, saved_username = load_saved_license()
    if not key and saved_key:
        key = saved_key.strip().upper()
    if not key:
        return {
            "status": "unauthorized",
            "plan": None,
            "limited": True,
            "binding_conflict": False,
            "message": "Enter your license key to reset its hardware binding.",
        }

    target_username = (
        saved_username
        if (saved_key and key == saved_key.strip().upper() and saved_username)
        else f"{LICENSE_PREFIX}_{key}"
    )
    try:
        resp = _post_with_retry(
            RESET_BINDING_API_URL,
            {"license_key": key, "username": target_username},
            timeout=20,
            retries=2,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code != 200:
            msg = data.get("message") or data.get("error") or "Failed to reset license binding."
            return {
                "status": "unauthorized",
                "plan": None,
                "limited": True,
                "binding_conflict": is_binding_conflict(msg),
                "message": msg,
            }

        save_license(key, target_username)
        _AUTH_CACHE["status"] = None
        auth_res = check_authorization(force=True)
        auth_res["reset"] = True
        if auth_res.get("status") == "authorized":
            auth_res["message"] = data.get("message") or "Hardware binding reset and license activated!"
        return auth_res
    except Exception as e:
        return {
            "status": "unreachable",
            "plan": None,
            "limited": True,
            "binding_conflict": False,
            "message": f"Connection error during binding reset: {e}",
        }


def use_free_tier():
    """Clear a conflicting/saved license key and fall back to the free tier."""
    clear_saved_license()
    return check_authorization(force=True)


def check_notifications(force=False):
    """Fetch active broadcast notifications from the Brain Lead server (cached)."""
    now = time.time()
    if not force and _NOTIF_CACHE["data"] is not None and (now - _NOTIF_CACHE["ts"]) < _NOTIF_CACHE["ttl"]:
        return _NOTIF_CACHE["data"]
    out = {"notification": None}
    try:
        url = f"{NOTIFICATION_API_URL}?admin_key={ADMIN_NOTIFICATION_KEY}"
        resp = _get_with_retry(url, timeout=8, retries=2)
        if resp.status_code == 200:
            data = resp.json() if resp.content else {}
            notifs = data.get("notifications") or {}
            general = [n for n in (notifs.get("general") or []) if n.get("active", True)]
            if general:
                item = general[0]
                out["notification"] = {
                    "message": item.get("message", ""),
                    "url": item.get("url", ""),
                }
    except Exception:
        pass
    _NOTIF_CACHE["data"] = out
    _NOTIF_CACHE["ts"] = now
    return out


def free_limits():
    """Caps applied to the free tier."""
    return {
        "max_results_per_search": FREE_MAX_RESULTS_PER_SEARCH,
        "area_scan_max_tiles": FREE_AREA_SCAN_MAX_TILES,
    }


def branding():
    """Branding + Telegram links for the frontend."""
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "app_id": APP_ID,
        "app_display_name": APP_DISPLAY_NAME,
        "developer": DEVELOPER,
        "telegram_personal": DEVELOPER_CONTACT,
        "telegram_personal_handle": DEVELOPER_TELEGRAM,
        "telegram_bot": TELEGRAM_BOT_URL,
        "telegram_bot_handle": DEVELOPER_BOT,
        "website": WEBSITE_URL,
        "buy_license_url": BUY_LICENSE_URL,
        "notink": notink,
    }
