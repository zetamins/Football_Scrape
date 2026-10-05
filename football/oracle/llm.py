"""Provider-agnostic JSON-out LLM client for the Oracle: Gemini, NVIDIA NIM, OpenRouter (free models), local Ollama.

* Keys come ONLY from the environment (GEMINI_API_KEY, NVIDIA_API_KEY, OPENROUTER_API_KEY) and are sent only in
  request headers; they are never logged, cached, or put in error text.
* Free tiers are rate limited (OpenRouter free: ~20 req/min and ~50/day; Gemini and NVIDIA vary), so every call is
  throttled per provider, retried with back-off on 429/5xx, and cached on disk keyed by (provider, model, prompts) --
  re-running the same match costs nothing and an evaluation is exactly repeatable.
* Models differ in JSON support, so the contract is prompt-specified JSON plus tolerant extraction; callers validate.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {"env": "GEMINI_API_KEY", "model": "gemini-3.8-flash", "interval": 6.0},
    "nvidia": {"env": "NVIDIA_API_KEY", "model": "nvidia/nemotron-3-super-120b-a12b", "interval": 2.0},
    "openrouter": {"env": "OPENROUTER_API_KEY", "model": "qwen/qwen3.8-27b:free", "interval": 4.0},
    "ollama": {"env": None, "model": os.environ.get("FOOTBALL_LLM_MODEL", "qwen3:1.7b"), "interval": 0.0},
}
# Gemini is selectable but not in the automatic chain: the project behind the current key is denied access by Google
# (HTTP 403 PERMISSION_DENIED on every generateContent call, although listing models works).
AUTO_ORDER = ("nvidia", "openrouter", "ollama")
# Default panel: different model families so their errors are less correlated (NVIDIA Nemotron x2, OpenAI gpt-oss, Alibaba Qwen).
# Measured: nemotron-3-super 1.6 s, nemotron-3-ultra 12 s, gpt-oss-20b 38 s, qwen3.8-27b:free 3 s; deepseek-v4.1-flash and glm-5.3-flash
# timed out at 90 s (congested) and kimi-k3 needed 64 s for a trivial prompt, so they are left out.
DEFAULT_PANEL = (
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
    ("nvidia", "openai/gpt-oss-20b"),
    ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),
    ("openrouter", "qwen/qwen3.8-27b:free"),
)
# Listed by NVIDIA but HTTP 404 for this account: mistral-large(-2), llama-3.1-nemotron-ultra-253b, nemotron-nano-3-30b, kimi-k2.6.
# google/gemma-4-31b-it:free on OpenRouter answered HTTP 429 (upstream free-tier rate limit) in testing, so it is not in the panel.
MAX_RETRIES = 3
TIMEOUT_S = 600
_last_call: dict[str, float] = {}
_throttle_lock = threading.Lock()
_cache_lock = threading.Lock()


def cache_path() -> Path:
    return Path(os.environ.get("ORACLE_LLM_CACHE", str(Path.home() / ".cache" / "football-oracle" / "llm-cache.jsonl")))


def available_providers() -> list[str]:
    """Providers usable right now: key present in the environment (ollama needs no key)."""
    return [p for p in AUTO_ORDER if PROVIDERS[p]["env"] is None or os.environ.get(PROVIDERS[p]["env"] or "")]


def default_panel() -> list[tuple[str, str]]:
    """DEFAULT_PANEL restricted to providers whose key is present; if none, the local Ollama model."""
    have = set(available_providers())
    panel = [(p, m) for p, m in DEFAULT_PANEL if p in have]
    return panel or [("ollama", PROVIDERS["ollama"]["model"])]


def _cache_key(provider: str, model: str, system: str, user: str) -> str:
    return hashlib.sha256("\x1f".join((provider, model, system, user)).encode()).hexdigest()


def _cache_load() -> dict[str, dict]:
    try:
        lines = cache_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out = {}
    for line in lines:
        try:
            rec = json.loads(line)
            out[rec["k"]] = rec["v"]
        except (ValueError, KeyError):
            continue
    return out


def _cache_store(key: str, value: dict) -> None:
    path = cache_path()
    with _cache_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"k": key, "v": value}, ensure_ascii=False) + "\n")


def extract_json(text: str) -> dict:
    """First JSON object in a reply (models wrap JSON in prose or ``` fences)."""
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


def _http(url: str, body: dict, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 -- fixed provider endpoints
        return json.loads(resp.read().decode())


def _call_gemini(model: str, system: str, user: str, key: str) -> str:
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 8192}}
    data = _http(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", body, {"x-goog-api-key": key})
    parts = (((data.get("candidates") or [{}])[0]).get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise OSError(f"empty Gemini reply (finish: {((data.get('candidates') or [{}])[0]).get('finishReason')})")
    return text


def _call_openai_compat(url: str, model: str, system: str, user: str, key: str, extra: dict | None = None) -> str:
    body = {"model": model, "temperature": 0, "max_tokens": 6000,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], **(extra or {})}
    data = _http(url, body, {"Authorization": f"Bearer {key}", "X-Title": "football-oracle"})
    msg = ((data.get("choices") or [{}])[0]).get("message") or {}
    text = msg.get("content") or ""
    if not text:
        raise OSError(f"empty reply ({(data.get('error') or {}).get('message', 'no error message')[:120]})")
    return text


def _call_ollama(model: str, system: str, user: str, _key: str) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    host = host if host.startswith("http") else "http://" + host
    body = {"model": model, "stream": False, "format": "json", "think": False, "keep_alive": "30s",
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1500, "seed": 7},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    return ((_http(f"{host}/api/chat", body, {}).get("message") or {}).get("content")) or ""


def _dispatch(provider: str, model: str, system: str, user: str, key: str) -> str:
    if provider == "gemini":
        return _call_gemini(model, system, user, key)
    if provider == "nvidia":
        return _call_openai_compat("https://integrate.api.nvidia.com/v1/chat/completions", model, system, user, key)
    if provider == "openrouter":
        return _call_openai_compat("https://openrouter.ai/api/v1/chat/completions", model, system, user, key)
    if provider == "ollama":
        return _call_ollama(model, system, user, key)
    raise ValueError(f"unknown provider {provider!r}")


def ask_json(provider: str, system: str, user: str, model: str | None = None, use_cache: bool = True) -> dict:
    """{'ok': True, 'provider', 'model', 'data': {...}, 'cached': bool} or {'ok': False, 'provider', 'error'}. Never raises."""
    if provider not in PROVIDERS:
        return {"ok": False, "provider": provider, "error": f"unknown provider {provider!r}"}
    cfg = PROVIDERS[provider]
    model = model or cfg["model"]
    ck = _cache_key(provider, model, system, user)
    if use_cache:
        hit = _cache_load().get(ck)
        if hit is not None:
            return {"ok": True, "provider": provider, "model": model, "data": hit, "cached": True}
    key = os.environ.get(cfg["env"]) if cfg["env"] else ""
    if cfg["env"] and not key:
        return {"ok": False, "provider": provider, "model": model, "error": f"{cfg['env']} is not set"}
    error = ""
    for attempt in range(MAX_RETRIES):
        with _throttle_lock:                                   # reserve the next slot for this provider, sleep outside the lock
            slot = max(time.monotonic(), _last_call.get(provider, 0.0) + cfg["interval"])
            _last_call[provider] = slot
        if slot > time.monotonic():
            time.sleep(slot - time.monotonic())
        try:
            data = extract_json(_dispatch(provider, model, system, user, key or ""))
            if use_cache:
                _cache_store(ck, data)
            return {"ok": True, "provider": provider, "model": model, "data": data, "cached": False}
        except ValueError as e:                     # unparseable reply: try once more, models are not fully deterministic
            error = f"{type(e).__name__}: {e}"
        except urllib.error.HTTPError as e:
            error = f"HTTP {e.code}"
            if e.code not in (408, 409, 425, 429, 500, 502, 503, 504):
                break                               # auth / bad request: retrying cannot help
            retry_after = e.headers.get("Retry-After") if e.headers else None
            time.sleep(min(60.0, float(retry_after)) if retry_after and retry_after.isdigit() else 10.0 * (attempt + 1))
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            error = f"{type(e).__name__}: {str(e)[:120]}"
            time.sleep(5.0 * (attempt + 1))
    return {"ok": False, "provider": provider, "model": model, "error": f"{error} (after {MAX_RETRIES} attempts)"}
