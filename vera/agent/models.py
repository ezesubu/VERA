"""Registro de proveedores LLM y descubrimiento de modelos.

ANTHROPIC es nativo (`anthropic.Anthropic`); OPENAI/GEMINI/LOCAL pasan por el
adaptador OpenAI-compatible (`vera.llm.openai_compat_client`). `list_models`
devuelve la lista estática del registro salvo para LOCAL (LM Studio), donde
descubre en vivo los modelos cargados vía `GET {base_url}/models`.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable, List, Optional

# Endpoint OpenAI-compatible de Google para Gemini.
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
_LOCAL_BASE = "http://172.21.80.1:1233/v1"

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
        "base_url": _LOCAL_BASE,
        "native": False,
        "needs_key": False,
        "discover": True,
        "models": [],
    },
}


def _default_http(url: str, timeout: float = 4.0) -> dict:
    """GET JSON. Inyectable/mockeable vía el parámetro `http` de list_models."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (url local controlada)
        return json.loads(resp.read().decode("utf-8"))


def has_key(provider: str) -> bool:
    """True si el proveedor no necesita key o la key está en el entorno."""
    spec = PROVIDERS.get(provider)
    if not spec:
        return False
    if not spec.get("needs_key"):
        return True
    env = spec.get("env")
    return bool(env and os.environ.get(env))


def list_models(provider: str, *, http: Optional[Callable] = None) -> dict:
    """Devuelve {provider, models, status}.

    status ∈ {"ok","missing_key","online","offline"}. Para LOCAL descubre en vivo
    (online/offline); para el resto devuelve la lista estática (ok/missing_key).
    """
    spec = PROVIDERS.get(provider)
    if not spec:
        return {"provider": provider, "models": [], "status": "missing_key"}

    if spec.get("discover"):
        http = http or _default_http
        url = spec["base_url"].rstrip("/") + "/models"
        try:
            data = http(url)
        except Exception:  # server local caído/inalcanzable
            return {"provider": provider, "models": [], "status": "offline"}
        ids = [m.get("id") for m in (data or {}).get("data", []) if m.get("id")]
        return {"provider": provider, "models": ids, "status": "online"}

    if spec.get("needs_key") and not has_key(provider):
        return {"provider": provider, "models": list(spec["models"]), "status": "missing_key"}
    return {"provider": provider, "models": list(spec["models"]), "status": "ok"}


def provider_status(provider: str) -> str:
    """Estado de credenciales sin tocar la red: ok | missing_key."""
    return "ok" if has_key(provider) else "missing_key"


def list_providers() -> List[dict]:
    """Lista para el selector de la UI: id, label, status, needs_key."""
    return [
        {
            "id": pid,
            "label": spec["label"],
            "status": provider_status(pid),
            "needs_key": bool(spec.get("needs_key")),
        }
        for pid, spec in PROVIDERS.items()
    ]
