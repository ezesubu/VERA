"""LLM provider registry and model discovery.

ANTHROPIC is native (`anthropic.Anthropic`); OPENAI/GEMINI/LOCAL go through the
OpenAI-compatible adapter (`vera.llm.openai_compat_client`). `list_models`
returns the registry's static list except for LOCAL (LM Studio), where it
discovers the loaded models live via `GET {base_url}/models`.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable, List, Optional

# Google's OpenAI-compatible endpoint for Gemini.
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _local_base_url() -> Optional[str]:
    """The local OpenAI-compatible server URL, from VERA_LOCAL_BASE_URL.

    No hardcoded default: any server that speaks the OpenAI `/v1` API works
    (LM Studio → http://localhost:1234/v1, Ollama → http://localhost:11434/v1,
    llama.cpp, vLLM, ...). Returns None when unset; LOCAL is then "not configured".
    """
    url = os.environ.get("VERA_LOCAL_BASE_URL")
    return url.rstrip("/") if url else None

PROVIDERS = {
    "ANTHROPIC": {
        "label": "Anthropic · Claude",
        "env": "ANTHROPIC_API_KEY",
        "base_url": None,
        "native": True,
        "needs_key": True,
        "discover": False,
        "models": ["claude-opus-4-8", "claude-sonnet-4-5", "claude-3-5-sonnet-20241022"],
    },
    "OPENAI": {
        "label": "OpenAI · GPT",
        "env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "native": False,
        "needs_key": True,
        "discover": False,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
    },
    "GEMINI": {
        "label": "Google · Gemini",
        "env": "GEMINI_API_KEY",
        "base_url": _GEMINI_BASE,
        "native": False,
        "needs_key": True,
        "discover": False,
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    },
    "LOCAL": {
        "label": "LM Studio · Local",
        "env": None,
        "base_url": None,  # resolved live from VERA_LOCAL_BASE_URL
        "native": False,
        "needs_key": False,
        "discover": True,
        "models": [],
    },
}


def base_url_for(provider: str) -> Optional[str]:
    """Effective base_url for `provider`. LOCAL reads VERA_LOCAL_BASE_URL live;
    the rest use the static registry value. None means "not configured"."""
    if provider == "LOCAL":
        return _local_base_url()
    spec = PROVIDERS.get(provider) or {}
    return spec.get("base_url")


def _default_http(url: str, timeout: float = 4.0) -> dict:
    """GET JSON. Injectable/mockable via the `http` parameter of list_models."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (controlled local url)
        return json.loads(resp.read().decode("utf-8"))


def has_key(provider: str) -> bool:
    """True if the provider needs no key or the key is in the environment."""
    spec = PROVIDERS.get(provider)
    if not spec:
        return False
    if not spec.get("needs_key"):
        return True
    env = spec.get("env")
    return bool(env and os.environ.get(env))


def list_models(provider: str, *, http: Optional[Callable] = None) -> dict:
    """Return {provider, models, status}.

    status ∈ {"ok","missing_key","online","offline"}. For LOCAL it discovers live
    (online/offline); for the rest it returns the static list (ok/missing_key).
    """
    spec = PROVIDERS.get(provider)
    if not spec:
        return {"provider": provider, "models": [], "status": "missing_key"}

    if spec.get("discover"):
        base = base_url_for(provider)
        if not base:  # no VERA_LOCAL_BASE_URL set → user must configure it
            return {"provider": provider, "models": [], "status": "not_configured"}
        http = http or _default_http
        url = base.rstrip("/") + "/models"
        try:
            data = http(url)
        except Exception:  # local server down/unreachable
            return {"provider": provider, "models": [], "status": "offline"}
        ids = [m.get("id") for m in (data or {}).get("data", []) if m.get("id")]
        return {"provider": provider, "models": ids, "status": "online"}

    if spec.get("needs_key") and not has_key(provider):
        return {"provider": provider, "models": list(spec["models"]), "status": "missing_key"}
    return {"provider": provider, "models": list(spec["models"]), "status": "ok"}


def provider_status(provider: str) -> str:
    """Config status without touching the network: ok | missing_key | not_configured."""
    if provider == "LOCAL":
        return "ok" if _local_base_url() else "not_configured"
    return "ok" if has_key(provider) else "missing_key"


def list_providers() -> List[dict]:
    """List for the UI selector: id, label, status, needs_key."""
    return [
        {
            "id": pid,
            "label": spec["label"],
            "status": provider_status(pid),
            "needs_key": bool(spec.get("needs_key")),
        }
        for pid, spec in PROVIDERS.items()
    ]


# Order VERA prefers when the caller doesn't pick a provider: a configured cloud
# provider first, then a local server. Lets a fresh install "just work" with
# whatever the user actually set up, instead of always assuming Anthropic.
_PROVIDER_PREFERENCE = ("ANTHROPIC", "OPENAI", "GEMINI", "LOCAL")


def default_provider() -> str:
    """The provider to use when none is explicitly selected: the first CONFIGURED
    provider in preference order, or ANTHROPIC as a last resort (so a fully
    unconfigured install gets a clear 'set a key' error, not a silent failure)."""
    for pid in _PROVIDER_PREFERENCE:
        if provider_status(pid) == "ok":
            return pid
    return "ANTHROPIC"


def default_model(provider: str) -> str:
    """A sensible model id for `provider` when none is chosen: the registry's
    first static model, or — for LOCAL — the first live-discovered model."""
    spec = PROVIDERS.get(provider) or {}
    static = spec.get("models") or []
    if static:
        return static[0]
    if spec.get("discover"):
        ids = list_models(provider).get("models") or []
        if ids:
            return ids[0]
    return ""
