"""Unified BYOK AI provider adapter (Gemini, Claude, ChatGPT/OpenAI, Ollama).

Uses direct REST calls via curl_cffi so no heavy external LLM SDKs are required.
"""
import asyncio
import json
import re
import time
import uuid
from curl_cffi import AsyncSession
from backend.ai import config_store

PROVIDER_MODELS = {
    "gemini": {
        "label": "Google Gemini",
        "fast": "gemini-2.5-flash-lite",
        "balanced": "gemini-2.5-flash",
        "best": "gemini-2.5-pro",
    },
    "claude": {
        "label": "Anthropic Claude",
        "fast": "claude-3-5-haiku-latest",
        "balanced": "claude-sonnet-4-5",
        "best": "claude-opus-4-1",
    },
    "openai": {
        "label": "OpenAI / ChatGPT",
        "fast": "gpt-4o-mini",
        "balanced": "gpt-4o",
        "best": "o3",
    },
    "ollama": {
        "label": "Local Ollama / Custom",
        "fast": "llama3.2",
        "balanced": "qwen2.5:14b",
        "best": "llama3.3:70b",
    },
}

# Ordered Small -> Balanced -> Big curated baseline per provider
CURATED_CATALOG: dict[str, list[dict]] = {
    "gemini": [
        {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash-Lite", "tier": "small", "note": "Smallest & lowest cost"},
        {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash-Lite", "tier": "small", "note": "Ultra-fast modern lite"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "tier": "small", "note": "Fast everyday model"},
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "tier": "balanced", "note": "Best speed & reasoning"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tier": "large", "note": "Big flagship reasoning"},
    ],
    "claude": [
        {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku", "tier": "small", "note": "Fast & lightweight"},
        {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "tier": "small", "note": "Fast modern compact model"},
        {"id": "claude-3-7-sonnet-latest", "name": "Claude 3.7 Sonnet", "tier": "balanced", "note": "Balanced reasoning"},
        {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "tier": "balanced", "note": "High-accuracy daily driver"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "tier": "balanced", "note": "Latest Sonnet model"},
        {"id": "claude-opus-4-1", "name": "Claude Opus 4.1", "tier": "large", "note": "Big deep research powerhouse"},
        {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "tier": "large", "note": "Largest flagship Claude"},
    ],
    "openai": [
        {"id": "gpt-4.1-nano", "name": "GPT-4.1 Nano", "tier": "small", "note": "Smallest & fastest"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "tier": "small", "note": "Fast & budget-friendly"},
        {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "tier": "small", "note": "Modern compact worker"},
        {"id": "gpt-5-mini", "name": "GPT-5 Mini", "tier": "small", "note": "Compact next-gen worker"},
        {"id": "gpt-4o", "name": "GPT-4o", "tier": "balanced", "note": "Reliable all-rounder"},
        {"id": "gpt-4.1", "name": "GPT-4.1", "tier": "balanced", "note": "Sharp instruction follower"},
        {"id": "o4-mini", "name": "o4-mini", "tier": "balanced", "note": "Fast analytical reasoning"},
        {"id": "o3", "name": "o3", "tier": "large", "note": "Deep complex reasoning"},
        {"id": "gpt-5", "name": "GPT-5", "tier": "large", "note": "Big flagship ChatGPT"},
    ],
    "ollama": [
        {"id": "llama3.2:1b", "name": "Llama 3.2 1B", "tier": "small", "note": "Tiny local (~1.3B)"},
        {"id": "qwen2.5:3b", "name": "Qwen 2.5 3B", "tier": "small", "note": "Fast small local"},
        {"id": "llama3.2", "name": "Llama 3.2 (3B)", "tier": "small", "note": "Compact default local"},
        {"id": "llama3.1:8b", "name": "Llama 3.1 8B", "tier": "balanced", "note": "Balanced 8B local"},
        {"id": "qwen2.5:7b", "name": "Qwen 2.5 7B", "tier": "balanced", "note": "Great tool calling 7B"},
        {"id": "qwen2.5:14b", "name": "Qwen 2.5 14B", "tier": "balanced", "note": "Strong 14B workstation"},
        {"id": "qwen2.5:32b", "name": "Qwen 2.5 32B", "tier": "large", "note": "Heavy 32B local"},
        {"id": "llama3.3:70b", "name": "Llama 3.3 70B", "tier": "large", "note": "Flagship 70B local"},
    ],
}

_TIER_ORDER = {"small": 0, "balanced": 1, "large": 2}
_CURATED_BY_ID = {
    prov: {m["id"]: m for m in items}
    for prov, items in CURATED_CATALOG.items()
}
_LIVE_MODEL_CACHE: dict[tuple[str, str, str], dict] = {}


class AIProviderError(RuntimeError):
    """Raised when an AI provider request fails or is unconfigured."""


def _parse_param_size(text: str) -> float | None:
    m = re.search(r"(?:^|[:\-_\s])(\d+(?:\.\d+)?)\s*b(?:\b|[-_]|$)", text or "", re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def classify_model(provider: str, model_id: str, display_name: str = "", param_hint: str = "") -> dict:
    """Assign Small / Balanced / Big tier + capability sort key for consistent Small->Big order."""
    mid = (model_id or "").strip()
    low = mid.lower()
    curated = _CURATED_BY_ID.get(provider, {}).get(mid)
    tier = curated["tier"] if curated else None
    note = curated.get("note", "") if curated else ""
    name = (curated.get("name") if curated else "") or (display_name or "").strip() or mid

    params_b = _parse_param_size(param_hint) or _parse_param_size(low)

    if tier is None:
        if any(tok in low for tok in ("nano", "flash-lite", "lite", "haiku", "mini", "micro", "tiny", "8b")) and "o4-mini" not in low:
            tier = "small"
        elif params_b is not None and params_b <= 5.0:
            tier = "small"
        elif (
            any(tok in low for tok in ("opus", "ultra", "gpt-5", "gpt-4.5", "o3", "o1"))
            or re.search(r"(?:^|[-_])pro(?:$|[-_])", low)
        ) and "mini" not in low:
            tier = "large"
        elif params_b is not None and params_b >= 25.0:
            tier = "large"
        else:
            tier = "balanced"

    # Compute fine capability rank within tier so list reads smallest -> biggest
    curated_idx = next(
        (i for i, item in enumerate(CURATED_CATALOG.get(provider, [])) if item["id"] == mid),
        None,
    )
    tier_idx = _TIER_ORDER.get(tier, 1)
    if params_b is not None:
        fine = params_b
    elif "nano" in low:
        fine = 1.0
    elif "lite" in low:
        fine = 2.0
    elif "haiku" in low or "mini" in low:
        fine = 4.0
    elif "flash" in low and "pro" not in low:
        fine = 10.0
    elif "sonnet" in low or "gpt-4o" in low or "gpt-4.1" in low:
        fine = 20.0
    elif "pro" in low or "opus" in low or "gpt-5" in low or low == "o3":
        fine = 50.0
    else:
        fine = 15.0

    # Parse version numbers e.g. 2.5, 4.1, 4-5 so newer/stronger sorts slightly later inside tier
    nums = [float(n) for n in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)", low)]
    ver_weight = sum(n / (10 ** i) for i, n in enumerate(nums[:2])) * 0.1 if nums else 0.0
    tier_label = {"small": "Small · Fast", "balanced": "Balanced", "large": "Big · Powerful"}.get(tier, "Balanced")
    rank_tuple = (tier_idx, curated_idx if curated_idx is not None else (fine + ver_weight), mid)
    return {
        "id": mid,
        "name": name,
        "tier": tier,
        "tier_label": tier_label,
        "note": note or (f"{param_hint}" if param_hint else tier_label),
        "_rank": rank_tuple,
    }


def sort_models_small_to_big(models: list[dict]) -> list[dict]:
    dedup: dict[str, dict] = {}
    for m in models:
        mid = m["id"]
        if mid not in dedup:
            dedup[mid] = m
    ordered = sorted(dedup.values(), key=lambda x: x.get("_rank", (1, 999, x["id"])))
    for m in ordered:
        m.pop("_rank", None)
    return ordered


def get_curated_models(provider: str) -> list[dict]:
    items = [
        classify_model(provider, m["id"], m["name"])
        for m in CURATED_CATALOG.get(provider, CURATED_CATALOG["gemini"])
    ]
    return sort_models_small_to_big(items)


def _is_chat_candidate(provider: str, model_id: str, custom_gateway: bool = False, extra: dict | None = None) -> bool:
    low = (model_id or "").lower()
    if not low:
        return False
    if provider == "gemini":
        methods = (extra or {}).get("supportedGenerationMethods") or []
        if methods and "generateContent" not in methods:
            return False
        if any(bad in low for bad in ("embedding", "aqa", "imagen", "veo", "tts", "audio", "robotics", "computer-use", "deep-research", "bisect")):
            return False
        return "gemini" in low or "gemma" in low
    if provider == "claude":
        return "claude" in low
    if provider == "openai":
        if custom_gateway:
            return not any(bad in low for bad in ("embedding", "whisper", "tts", "dall-e"))
        if any(bad in low for bad in ("embedding", "whisper", "tts", "dall-e", "moderation", "babbage", "davinci", "realtime", "audio", "transcribe", "image", "sora", "instruct", "codex")):
            return False
        return low.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))
    return True


async def fetch_available_models(provider: str | None = None, api_key: str | None = None,
                                 base_url: str | None = None, force_refresh: bool = False) -> dict:
    """Fetch live available models from provider API (or curated fallback), sorted Small -> Big."""
    rt = config_store.get_runtime_config()
    prov = provider or rt["provider"]
    eff_key = api_key if api_key is not None else (
        rt["api_key"] if prov == rt["provider"] else config_store.get_api_key(prov)
    )
    eff_base = (base_url if base_url is not None else rt.get("base_url", "")).strip()
    curated = get_curated_models(prov)

    if prov != "ollama" and not eff_key:
        return {
            "provider": prov,
            "source": "curated",
            "live_count": 0,
            "models": curated,
            "note": "Paste an API key and click Refresh Models to fetch your account's exact live models.",
        }

    cache_key = (prov, eff_base, (eff_key[-8:] if eff_key else ""))
    if not force_refresh and cache_key in _LIVE_MODEL_CACHE:
        return _LIVE_MODEL_CACHE[cache_key]

    live_items: list[dict] = []
    err_msg = ""
    try:
        async with AsyncSession(timeout=20) as session:
            if prov == "gemini":
                page_token = ""
                for _ in range(3):
                    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100"
                    if page_token:
                        url += f"&pageToken={page_token}"
                    resp = await session.get(url, headers={"x-goog-api-key": eff_key})
                    data = resp.json()
                    if resp.status_code >= 400:
                        raise AIProviderError(data.get("error", {}).get("message") or f"HTTP {resp.status_code}")
                    for m in data.get("models") or []:
                        mid = (m.get("name") or "").replace("models/", "")
                        if _is_chat_candidate("gemini", mid, extra=m):
                            live_items.append(classify_model("gemini", mid, m.get("displayName", "")))
                    page_token = data.get("nextPageToken") or ""
                    if not page_token:
                        break

            elif prov == "claude":
                url = "https://api.anthropic.com/v1/models?limit=100"
                headers = {
                    "x-api-key": eff_key,
                    "anthropic-version": "2023-06-01",
                }
                resp = await session.get(url, headers=headers)
                data = resp.json()
                if resp.status_code >= 400:
                    raise AIProviderError(data.get("error", {}).get("message") or f"HTTP {resp.status_code}")
                for m in data.get("data") or []:
                    mid = m.get("id") or ""
                    if _is_chat_candidate("claude", mid):
                        live_items.append(classify_model("claude", mid, m.get("display_name", "")))

            elif prov == "openai":
                base = (eff_base or "https://api.openai.com/v1").rstrip("/")
                custom_gw = "api.openai.com" not in base
                resp = await session.get(
                    f"{base}/models",
                    headers={"Authorization": f"Bearer {eff_key}"},
                )
                data = resp.json()
                if resp.status_code >= 400:
                    raise AIProviderError(data.get("error", {}).get("message") or f"HTTP {resp.status_code}")
                for m in data.get("data") or []:
                    mid = m.get("id") or ""
                    if _is_chat_candidate("openai", mid, custom_gateway=custom_gw):
                        live_items.append(classify_model("openai", mid))

            elif prov == "ollama":
                base = (eff_base or "http://127.0.0.1:11434/v1").rstrip("/")
                root = base[:-3] if base.endswith("/v1") else base
                # Try native /api/tags first (gives exact parameter_size!)
                got_ollama = False
                try:
                    resp = await session.get(f"{root}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        for m in data.get("models") or []:
                            mid = m.get("name") or ""
                            psize = ((m.get("details") or {}).get("parameter_size") or "")
                            if mid:
                                live_items.append(classify_model("ollama", mid, mid, param_hint=psize))
                        got_ollama = True
                except Exception:
                    pass
                if not got_ollama:
                    headers = {"Authorization": f"Bearer {eff_key}"} if eff_key else {}
                    resp2 = await session.get(f"{base}/models", headers=headers)
                    data2 = resp2.json()
                    if resp2.status_code >= 400:
                        raise AIProviderError(f"HTTP {resp2.status_code}")
                    for m in data2.get("data") or []:
                        mid = m.get("id") or ""
                        if mid:
                            live_items.append(classify_model("ollama", mid))
    except Exception as e:
        err_msg = str(e)

    if live_items:
        ordered = sort_models_small_to_big(live_items)
        result = {
            "provider": prov,
            "source": "live",
            "live_count": len(ordered),
            "models": ordered,
            "note": f"Fetched {len(ordered)} live models from {PROVIDER_MODELS[prov]['label']} (ordered Small → Big).",
        }
        _LIVE_MODEL_CACHE[cache_key] = result
        return result

    return {
        "provider": prov,
        "source": "curated",
        "live_count": 0,
        "models": curated,
        "error": err_msg,
        "note": err_msg or "Showing built-in models (Small → Big).",
    }


def resolve_model(provider: str, tier: str = "fast", custom_model: str = "") -> str:
    if (custom_model or "").strip():
        return custom_model.strip()
    meta = PROVIDER_MODELS.get(provider, PROVIDER_MODELS["gemini"])
    tier_map = {"small": "fast", "fast": "fast", "balanced": "balanced", "best": "best", "large": "best"}
    mapped = tier_map.get(tier, "fast")
    return meta.get(mapped, meta["fast"])


def _extract_json_text(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
        s = s.strip()
    # Try direct slice from first { or [
    for opener, closer in (("{", "}"), ("[", "]")):
        i = s.find(opener)
        j = s.rfind(closer)
        if i != -1 and j > i:
            return s[i : j + 1]
    return s


def parse_json_loose(raw: str):
    txt = _extract_json_text(raw)
    try:
        return json.loads(txt)
    except Exception:
        # Remove trailing commas before } or ]
        cleaned = re.sub(r",\s*([}\]])", r"\1", txt)
        return json.loads(cleaned)


def _sanitize_gemini_schema(schema):
    """Strip JSON Schema keys Gemini's functionDeclarations rejects."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in ("additionalProperties", "$schema", "default"):
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _sanitize_gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _sanitize_gemini_schema(v)
        else:
            out[k] = v
    return out


async def _post_json(url: str, headers: dict, payload: dict, timeout: int = 60, retries: int = 3) -> dict:
    last_err = None
    async with AsyncSession(timeout=timeout) as session:
        for attempt in range(retries):
            try:
                resp = await session.post(url, headers=headers, json=payload)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    await asyncio.sleep((2 ** attempt) + 0.5)
                    continue
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text[:500]}
                if resp.status_code >= 400:
                    err_msg = (
                        (data.get("error") or {}).get("message")
                        if isinstance(data.get("error"), dict)
                        else data.get("error") or data.get("message") or f"HTTP {resp.status_code}"
                    )
                    raise AIProviderError(f"{err_msg}")
                return data
            except AIProviderError:
                raise
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise AIProviderError(f"AI connection error: {e}")
    raise AIProviderError(str(last_err or "AI request failed"))


# ---------------------------------------------------------------------------
# Provider-specific payload builders & response parsers
# ---------------------------------------------------------------------------
def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    contents = []
    for m in messages:
        role = m["role"]
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": m.get("content") or ""}]})
        elif role == "assistant":
            # Echo exact model parts (preserves thought & thoughtSignature on Gemini 2.5/3 thinking models)
            if m.get("gemini_parts"):
                contents.append({"role": "model", "parts": m["gemini_parts"]})
                continue
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                part = {"functionCall": {"name": tc["name"], "args": tc.get("arguments") or {}}}
                if tc.get("thought_signature"):
                    part["thoughtSignature"] = tc["thought_signature"]
                parts.append(part)
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            # Gemini expects tool responses as functionResponse inside a user turn; merge consecutive tool turns
            try:
                resp_obj = json.loads(m["content"]) if isinstance(m["content"], str) else m["content"]
                if not isinstance(resp_obj, dict):
                    resp_obj = {"result": resp_obj}
            except Exception:
                resp_obj = {"result": str(m.get("content") or "")}
            part = {"functionResponse": {"name": m["name"], "response": resp_obj}}
            if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
    return contents


async def _call_gemini(model: str, api_key: str, system_prompt: str, messages: list[dict],
                       tools: list[dict] | None = None, json_mode: bool = False,
                       temperature: float = 0.2) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    budget = get_context_budget("gemini", model)
    payload: dict = {
        "contents": _to_gemini_contents(messages),
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": budget["max_output_tokens"],
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    if json_mode and not tools:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    if tools:
        payload["tools"] = [{
            "functionDeclarations": [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": _sanitize_gemini_schema(t.get("parameters", {"type": "object", "properties": {}})),
                }
                for t in tools
            ]
        }]

    data = await _post_json(
        url,
        {"Content-Type": "application/json", "x-goog-api-key": api_key},
        payload,
    )
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    texts, tool_calls = [], []
    for p in parts:
        if "text" in p and not p.get("thought"):
            texts.append(p["text"])
        elif "functionCall" in p:
            fc = p["functionCall"]
            tc = {
                "id": "call_" + uuid.uuid4().hex[:10],
                "name": fc.get("name", ""),
                "arguments": fc.get("args") or {},
            }
            ts = p.get("thoughtSignature") or p.get("thought_signature")
            if ts:
                tc["thought_signature"] = ts
            tool_calls.append(tc)
    return {
        "text": "\n".join(texts).strip(),
        "tool_calls": tool_calls,
        "gemini_parts": parts,
        "usage": _norm_usage("gemini", data),
    }


def _estimate_tokens(obj) -> int:
    if obj is None:
        return 0
    if isinstance(obj, str):
        return max(1, len(obj) // 4) if obj else 0
    try:
        return max(1, len(json.dumps(obj, ensure_ascii=False)) // 4)
    except Exception:
        return max(1, len(str(obj)) // 4)


def get_context_budget(provider: str, model: str = "") -> dict:
    """Return safe input/output token budgets tailored to provider & model size."""
    low = (model or "").lower()
    if provider == "gemini":
        return {"window_tokens": 1_000_000, "max_input_tokens": 90_000, "max_output_tokens": 8192}
    if provider == "claude":
        return {"window_tokens": 200_000, "max_input_tokens": 65_000, "max_output_tokens": 8192}
    if provider == "openai":
        if low.startswith(("o1", "o3", "o4", "gpt-5")):
            return {"window_tokens": 200_000, "max_input_tokens": 65_000, "max_output_tokens": 12_288}
        if low.startswith("gpt-4.1"):
            return {"window_tokens": 1_000_000, "max_input_tokens": 75_000, "max_output_tokens": 8192}
        return {"window_tokens": 128_000, "max_input_tokens": 50_000, "max_output_tokens": 4096}
    # Ollama / local open models (tighter context windows & speed)
    if any(k in low for k in ("70b", "72b", "32b", "14b", "qwen")):
        return {"window_tokens": 32_768, "max_input_tokens": 14_000, "max_output_tokens": 3072}
    return {"window_tokens": 16_384, "max_input_tokens": 7_500, "max_output_tokens": 2048}


def _norm_usage(provider: str, data: dict) -> dict:
    if provider == "gemini":
        m = data.get("usageMetadata") or {}
        return {
            "input_tokens": int(m.get("promptTokenCount") or 0),
            "cached_tokens": int(m.get("cachedContentTokenCount") or 0),
            "output_tokens": int((m.get("candidatesTokenCount") or 0) + (m.get("thoughtsTokenCount") or 0)),
        }
    if provider == "claude":
        u = data.get("usage") or {}
        cached = int(u.get("cache_read_input_tokens") or 0)
        created = int(u.get("cache_creation_input_tokens") or 0)
        return {
            "input_tokens": int(u.get("input_tokens") or 0) + cached + created,
            "cached_tokens": cached,
            "cache_created_tokens": created,
            "output_tokens": int(u.get("output_tokens") or 0),
        }
    u = data.get("usage") or {}
    cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    return {
        "input_tokens": int(u.get("prompt_tokens") or 0),
        "cached_tokens": cached,
        "output_tokens": int(u.get("completion_tokens") or 0),
    }


def fit_messages_to_context_window(messages: list[dict], system_prompt: str = "",
                                   tools: list[dict] | None = None,
                                   provider: str = "gemini", model: str = "") -> list[dict]:
    """Keep conversation strictly inside safe token budgets while preserving valid tool pairing."""
    if not messages:
        return []
    budget = get_context_budget(provider, model)
    prefix_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(tools or [])
    msg_budget = max(2048, budget["max_input_tokens"] - prefix_tokens)

    work = [dict(m) for m in messages]
    total = sum(_estimate_tokens(m) for m in work)
    if total <= msg_budget:
        return work

    # Stage 1: Compact older tool outputs outside the last 6 messages (preserves exact tool pairing & prefix).
    cutoff = max(1, len(work) - 6)
    for i in range(1, cutoff):
        if work[i].get("role") == "tool":
            raw = str(work[i].get("content") or "")
            if len(raw) > 400:
                work[i]["content"] = json.dumps({
                    "_compacted": True,
                    "tool": work[i].get("name") or "tool",
                    "excerpt": raw[:320],
                }, ensure_ascii=False)
                total = sum(_estimate_tokens(m) for m in work)
                if total <= msg_budget:
                    return work

    # Stage 2: Group into atomic turns and drop oldest complete turns after message 0 until within budget.
    groups: list[list[dict]] = []
    i = 0
    while i < len(work):
        cur = [work[i]]
        if work[i].get("role") == "assistant" and work[i].get("tool_calls"):
            j = i + 1
            while j < len(work) and work[j].get("role") == "tool":
                cur.append(work[j])
                j += 1
            i = j
        else:
            i += 1
        groups.append(cur)

    # Always keep group 0 (user goal) and the latest 2 groups intact when possible.
    while len(groups) > 3 and sum(_estimate_tokens(g) for g in groups) > msg_budget:
        groups.pop(1)

    flattened: list[dict] = []
    for g in groups:
        flattened.extend(g)
    return flattened


def _is_openai_reasoning(model: str) -> bool:
    low = (model or "").lower()
    return low.startswith(("o1", "o3", "o4", "gpt-5"))


def _to_claude_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m.get("content") or ""})
        elif role == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc.get("arguments") or {},
                })
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or "",
                "content": str(m.get("content") or ""),
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


async def _call_claude(model: str, api_key: str, system_prompt: str, messages: list[dict],
                       tools: list[dict] | None = None, temperature: float = 0.2) -> dict:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    budget = get_context_budget("claude", model)
    claude_msgs = _to_claude_messages(messages)
    # Mark penultimate message block as ephemeral cache breakpoint during long tool loops
    if len(claude_msgs) >= 4:
        target = claude_msgs[-2]
        if isinstance(target.get("content"), list) and target["content"]:
            target["content"][-1] = {**target["content"][-1], "cache_control": {"type": "ephemeral"}}
        elif isinstance(target.get("content"), str) and target["content"]:
            target["content"] = [{"type": "text", "text": target["content"], "cache_control": {"type": "ephemeral"}}]

    payload: dict = {
        "model": model,
        "max_tokens": budget["max_output_tokens"],
        "temperature": temperature,
        "messages": claude_msgs,
    }
    if system_prompt:
        payload["system"] = [
            {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
        ]
    if tools:
        claude_tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]
        claude_tools[-1]["cache_control"] = {"type": "ephemeral"}
        payload["tools"] = claude_tools

    data = await _post_json(url, headers, payload)
    texts, tool_calls = [], []
    for blk in data.get("content") or []:
        if blk.get("type") == "text":
            texts.append(blk.get("text", ""))
        elif blk.get("type") == "tool_use":
            tool_calls.append({
                "id": blk.get("id") or ("call_" + uuid.uuid4().hex[:10]),
                "name": blk.get("name", ""),
                "arguments": blk.get("input") or {},
            })
    return {
        "text": "\n".join(texts).strip(),
        "tool_calls": tool_calls,
        "usage": _norm_usage("claude", data),
    }


def _to_openai_messages(system_prompt: str, messages: list[dict]) -> list[dict]:
    out = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m.get("content") or ""})
        elif role == "assistant":
            msg: dict = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("arguments") or {}),
                        },
                    }
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id") or "",
                "content": str(m.get("content") or ""),
            })
    return out


async def _call_openai_compat(model: str, api_key: str, base_url: str, system_prompt: str,
                               messages: list[dict], tools: list[dict] | None = None,
                               json_mode: bool = False, temperature: float = 0.2) -> dict:
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    is_openai_official = "api.openai.com" in url
    is_reasoning = is_openai_official and _is_openai_reasoning(model)
    budget = get_context_budget("openai" if is_openai_official else "ollama", model)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict = {
        "model": model,
        "messages": _to_openai_messages(system_prompt, messages),
    }
    if not is_reasoning:
        payload["temperature"] = temperature
    if is_openai_official:
        payload["max_completion_tokens"] = budget["max_output_tokens"]
    if json_mode and not tools and is_openai_official:
        payload["response_format"] = {"type": "json_object"}
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    data = await _post_json(url, headers, payload)
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            args = {}
        tool_calls.append({
            "id": tc.get("id") or ("call_" + uuid.uuid4().hex[:10]),
            "name": fn.get("name", ""),
            "arguments": args,
        })
    return {
        "text": (msg.get("content") or "").strip(),
        "tool_calls": tool_calls,
        "usage": _norm_usage("openai", data),
    }


def _resolve_runtime(provider=None, tier=None, model=None, api_key=None, base_url=None):
    rt = config_store.get_runtime_config()
    prov = provider or rt["provider"]
    effective_key = api_key if api_key is not None else (
        rt["api_key"] if prov == rt["provider"] else config_store.get_api_key(prov)
    )
    effective_tier = tier or rt["tier"]
    saved_mod = config_store.get_selected_model(prov)
    effective_model = model or resolve_model(prov, effective_tier, saved_mod)
    effective_base = base_url if base_url is not None else rt["base_url"]
    if prov != "ollama" and not effective_key:
        raise AIProviderError(f"No API key configured for {PROVIDER_MODELS.get(prov, {}).get('label', prov)}. Add one in Settings → AI Engine.")
    if prov == "ollama" and not effective_base:
        effective_base = "http://127.0.0.1:11434/v1"
    return prov, effective_model, effective_key, effective_base


async def run_tool_turn(messages: list[dict], tools: list[dict] | None = None,
                        system_prompt: str = "", provider: str | None = None,
                        tier: str | None = None, model: str | None = None,
                        api_key: str | None = None, base_url: str | None = None,
                        temperature: float = 0.2) -> dict:
    prov, mod, key, burl = _resolve_runtime(provider, tier, model, api_key, base_url)
    fitted = fit_messages_to_context_window(
        messages, system_prompt=system_prompt, tools=tools, provider=prov, model=mod
    )
    if prov == "gemini":
        return await _call_gemini(mod, key, system_prompt, fitted, tools=tools, temperature=temperature)
    if prov == "claude":
        return await _call_claude(mod, key, system_prompt, fitted, tools=tools, temperature=temperature)
    return await _call_openai_compat(mod, key, burl, system_prompt, fitted, tools=tools, temperature=temperature)


async def complete_json(system_prompt: str, user_prompt: str,
                        provider: str | None = None, tier: str | None = None,
                        model: str | None = None, api_key: str | None = None,
                        base_url: str | None = None, temperature: float = 0.15) -> dict | list:
    prov, mod, key, burl = _resolve_runtime(provider, tier, model, api_key, base_url)
    msgs = [{"role": "user", "content": user_prompt}]
    sys_p = (system_prompt + "\n\nRespond ONLY with valid JSON. No markdown fences or extra commentary.").strip()
    if prov == "gemini":
        res = await _call_gemini(mod, key, sys_p, msgs, json_mode=True, temperature=temperature)
    elif prov == "claude":
        res = await _call_claude(mod, key, sys_p, msgs, temperature=temperature)
    else:
        res = await _call_openai_compat(mod, key, burl, sys_p, msgs, json_mode=True, temperature=temperature)
    raw = res.get("text") or ""
    try:
        return parse_json_loose(raw)
    except Exception:
        # One automatic repair attempt
        repair_msgs = [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": raw[:2000]},
            {"role": "user", "content": "Your previous output was not valid JSON. Return ONLY valid JSON matching the requested schema."},
        ]
        if prov == "gemini":
            res2 = await _call_gemini(mod, key, sys_p, repair_msgs, json_mode=True, temperature=0.0)
        elif prov == "claude":
            res2 = await _call_claude(mod, key, sys_p, repair_msgs, temperature=0.0)
        else:
            res2 = await _call_openai_compat(mod, key, burl, sys_p, repair_msgs, json_mode=True, temperature=0.0)
        return parse_json_loose(res2.get("text") or "{}")


async def test_connection(provider: str | None = None, tier: str | None = None,
                          model: str | None = None, api_key: str | None = None,
                          base_url: str | None = None) -> dict:
    t0 = time.time()
    prov, mod, key, burl = _resolve_runtime(provider, tier, model, api_key, base_url)
    data = await complete_json(
        "You are a connection health check.",
        'Return {"ok": true}',
        provider=prov,
        model=mod,
        api_key=key,
        base_url=burl,
        temperature=0.0,
    )
    ms = int((time.time() - t0) * 1000)
    return {
        "ok": bool(isinstance(data, dict) and data.get("ok", True)),
        "provider": prov,
        "model": mod,
        "latency_ms": ms,
    }
