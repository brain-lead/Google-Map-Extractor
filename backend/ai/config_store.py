"""Encrypted AI configuration store (API keys, provider, model tier, guardrails)."""
import base64
import json
from pathlib import Path
from backend import config as cfg

DEFAULT_GUARDRAILS = {
    "max_searches": 5,
    "max_scrapes": 100,
    "max_deep_leads": 25,
    "max_steps": 18,
}

PROVIDERS = ("gemini", "claude", "openai", "ollama")


def _config_path() -> Path:
    return cfg.DATA_DIR / "ai_config.json"


def _enc_secret(raw: str) -> str:
    if not raw:
        return ""
    token = cfg.encrypt_bytes(raw.encode("utf-8"))
    return base64.b64encode(token).decode("ascii")


def _dec_secret(enc: str) -> str:
    if not enc:
        return ""
    try:
        raw = base64.b64decode(enc.encode("ascii"))
        return cfg.decrypt_bytes(raw).decode("utf-8")
    except Exception:
        return ""


def _mask(secret: str) -> str:
    s = (secret or "").strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "••••" + s[-2:]
    return s[:4] + "••••" + s[-4:]


def _default_doc() -> dict:
    return {
        "provider": "gemini",
        "tier": "fast",
        "custom_model": "",
        "selected_models": {p: "" for p in PROVIDERS},
        "base_url": "",
        "keys": {p: "" for p in PROVIDERS},
        "guardrails": dict(DEFAULT_GUARDRAILS),
    }


def load_raw() -> dict:
    p = _config_path()
    doc = _default_doc()
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                if saved.get("provider") in PROVIDERS:
                    doc["provider"] = saved["provider"]
                if saved.get("tier") in ("small", "fast", "balanced", "best", "large"):
                    doc["tier"] = saved["tier"]
                doc["custom_model"] = str(saved.get("custom_model") or "")
                if isinstance(saved.get("selected_models"), dict):
                    for k in PROVIDERS:
                        if saved["selected_models"].get(k):
                            doc["selected_models"][k] = str(saved["selected_models"][k])
                if doc["custom_model"] and not doc["selected_models"].get(doc["provider"]):
                    doc["selected_models"][doc["provider"]] = doc["custom_model"]
                doc["base_url"] = str(saved.get("base_url") or "")
                if isinstance(saved.get("keys"), dict):
                    for k in PROVIDERS:
                        if saved["keys"].get(k):
                            doc["keys"][k] = str(saved["keys"][k])
                if isinstance(saved.get("guardrails"), dict):
                    for g, dv in DEFAULT_GUARDRAILS.items():
                        try:
                            val = int(saved["guardrails"].get(g, dv))
                            doc["guardrails"][g] = max(1, val)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            pass
    return doc


def get_selected_model(provider: str | None = None) -> str:
    doc = load_raw()
    prov = provider or doc["provider"]
    sel = (doc.get("selected_models") or {}).get(prov, "")
    if sel:
        return sel
    if prov == doc["provider"]:
        return doc.get("custom_model") or ""
    return ""


def get_api_key(provider: str | None = None) -> str:
    doc = load_raw()
    prov = provider or doc["provider"]
    return _dec_secret(doc["keys"].get(prov, ""))


def is_configured(provider: str | None = None) -> bool:
    doc = load_raw()
    prov = provider or doc["provider"]
    if prov == "ollama":
        return bool((doc.get("base_url") or "http://127.0.0.1:11434/v1").strip())
    return bool(get_api_key(prov))


def get_runtime_config() -> dict:
    doc = load_raw()
    prov = doc["provider"]
    return {
        "provider": prov,
        "tier": doc["tier"],
        "custom_model": get_selected_model(prov),
        "selected_models": doc["selected_models"],
        "base_url": doc["base_url"],
        "api_key": get_api_key(prov),
        "guardrails": doc["guardrails"],
        "configured": is_configured(prov),
    }


def public_config() -> dict:
    """Safe frontend representation — never returns raw API keys."""
    doc = load_raw()
    prov = doc["provider"]
    keys_status = {}
    keys_masked = {}
    for p in PROVIDERS:
        plain = _dec_secret(doc["keys"].get(p, ""))
        masked = _mask(plain)
        keys_masked[p] = masked
        keys_status[p] = {
            "configured": True if p == "ollama" else bool(plain),
            "preview": masked,
        }
    return {
        "provider": prov,
        "tier": doc["tier"],
        "custom_model": get_selected_model(prov),
        "selected_models": doc["selected_models"],
        "base_url": doc["base_url"],
        "keys": keys_masked,
        "keys_status": keys_status,
        "guardrails": doc["guardrails"],
        "configured": is_configured(prov),
    }


def save_config(payload: dict) -> dict:
    doc = load_raw()
    if payload.get("provider") in PROVIDERS:
        doc["provider"] = payload["provider"]
    if payload.get("tier") in ("small", "fast", "balanced", "best", "large"):
        doc["tier"] = payload["tier"]
    prov = doc["provider"]
    if "model" in payload or "custom_model" in payload:
        chosen = str(payload.get("model") if "model" in payload else payload.get("custom_model") or "").strip()
        doc["custom_model"] = chosen
        doc["selected_models"][prov] = chosen
    if isinstance(payload.get("selected_models"), dict):
        for p in PROVIDERS:
            if p in payload["selected_models"]:
                doc["selected_models"][p] = str(payload["selected_models"][p] or "").strip()
    if "base_url" in payload:
        doc["base_url"] = str(payload.get("base_url") or "").strip()

    # Accept {api_key: "..."} OR {keys: {...}} OR {api_keys: {...}}
    key_map = payload.get("keys") if isinstance(payload.get("keys"), dict) else payload.get("api_keys")
    if isinstance(key_map, dict):
        for p in PROVIDERS:
            if p in key_map:
                val = str(key_map[p] or "").strip()
                doc["keys"][p] = _enc_secret(val) if val else ""
    if "api_key" in payload:
        val = str(payload.get("api_key") or "").strip()
        prov = doc["provider"]
        if val:
            doc["keys"][prov] = _enc_secret(val)
        elif payload.get("clear_key"):
            doc["keys"][prov] = ""

    if isinstance(payload.get("guardrails"), dict):
        g = payload["guardrails"]
        limits = {
            "max_searches": (1, 20),
            "max_scrapes": (10, 1000),
            "max_deep_leads": (1, 150),
            "max_steps": (4, 40),
        }
        for k, (lo, hi) in limits.items():
            if k in g:
                try:
                    doc["guardrails"][k] = max(lo, min(hi, int(g[k])))
                except (TypeError, ValueError):
                    pass

    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_config()
