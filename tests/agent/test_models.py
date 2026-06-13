"""Tests del registro de proveedores y list_models (con http fake)."""
import json

import pytest

from vera.agent import models


# ---------------- registro estático ----------------

def test_providers_registry_has_four_known_providers():
    assert set(models.PROVIDERS) >= {"ANTHROPIC", "OPENAI", "GEMINI", "LOCAL"}


def test_anthropic_is_native_and_needs_key():
    p = models.PROVIDERS["ANTHROPIC"]
    assert p["native"] is True
    assert p["env"] == "ANTHROPIC_API_KEY"
    assert p["needs_key"] is True


def test_local_default_base_url():
    assert models.PROVIDERS["LOCAL"]["base_url"] == "http://172.21.80.1:1233/v1"
    assert models.PROVIDERS["LOCAL"]["needs_key"] is False


def test_gemini_base_url_is_openai_compatible_endpoint():
    assert "openai" in models.PROVIDERS["GEMINI"]["base_url"]


# ---------------- list_models: estáticos ----------------

def test_list_models_static_for_openai_when_key_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = models.list_models("OPENAI")
    assert out["provider"] == "OPENAI"
    assert out["status"] == "ok"
    assert isinstance(out["models"], list) and out["models"]


def test_list_models_missing_key_status(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = models.list_models("OPENAI")
    assert out["status"] == "missing_key"


def test_list_models_anthropic_static(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    out = models.list_models("ANTHROPIC")
    assert out["status"] == "ok"
    assert any("claude" in m for m in out["models"])


# ---------------- list_models: LOCAL autodescubrimiento ----------------

def _fake_http(payload=None, raise_exc=None):
    """Devuelve un callable http(url)->dict que imita un GET .../models."""
    def http(url, timeout=None):
        if raise_exc is not None:
            raise raise_exc
        return payload
    return http


def test_list_models_local_discovers_live():
    payload = {"data": [{"id": "qwen2.5-coder-32b"}, {"id": "llama-3.3-70b"}]}
    out = models.list_models("LOCAL", http=_fake_http(payload))
    assert out["provider"] == "LOCAL"
    assert out["status"] == "online"
    assert out["models"] == ["qwen2.5-coder-32b", "llama-3.3-70b"]


def test_list_models_local_offline_when_http_raises():
    out = models.list_models("LOCAL", http=_fake_http(raise_exc=OSError("conn refused")))
    assert out["status"] == "offline"
    assert out["models"] == []


def test_list_models_unknown_provider():
    out = models.list_models("NOPE")
    assert out["status"] == "missing_key" or out["models"] == []


# ---------------- provider_status / list_providers ----------------

def test_list_providers_returns_status_and_needs_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    provs = models.list_providers()
    by_id = {p["id"]: p for p in provs}
    assert by_id["ANTHROPIC"]["status"] == "ok"
    assert by_id["OPENAI"]["status"] == "missing_key"
    assert by_id["LOCAL"]["needs_key"] is False
    assert "label" in by_id["LOCAL"]
