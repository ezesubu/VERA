"""Tests de make_llm_client por proveedor y build_agent_loop con provider/model."""
import pytest

from vera.agent import factory


def test_make_llm_client_anthropic_returns_anthropic(monkeypatch):
    created = {}

    class FakeAnthropic:
        def __init__(self, *a, **k):
            created["yes"] = True

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    client = factory.make_llm_client("ANTHROPIC", "claude-opus-4-8")
    assert isinstance(client, FakeAnthropic)
    assert created["yes"]


def test_make_llm_client_local_returns_compat_client(monkeypatch):
    # LOCAL no necesita key ni red: el OpenAICompatClient se construye con un
    # cliente openai real solo en producción, pero acá inyectamos vía openai mock.
    import vera.llm.openai_compat_client as occ

    class FakeOpenAI:
        def __init__(self, *a, **k):
            self.kwargs = k

    # openai no está instalado en CI → parchear el import dentro del cliente
    import sys, types
    fake_openai_mod = types.ModuleType("openai")
    fake_openai_mod.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)

    client = factory.make_llm_client("LOCAL", "qwen-32b")
    assert isinstance(client, occ.OpenAICompatClient)
    assert client.model == "qwen-32b"
    assert client.base_url == "http://172.21.80.1:1233/v1"


def test_make_llm_client_openai_uses_env_key(monkeypatch):
    import sys, types
    captured = {}

    class FakeOpenAI:
        def __init__(self, *a, **k):
            captured.update(k)

    fake_openai_mod = types.ModuleType("openai")
    fake_openai_mod.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")

    client = factory.make_llm_client("OPENAI", "gpt-4o")
    assert client.model == "gpt-4o"
    assert captured["api_key"] == "sk-secret"
    assert captured["base_url"] == "https://api.openai.com/v1"


def test_make_llm_client_unknown_provider_raises():
    with pytest.raises(ValueError):
        factory.make_llm_client("NOPE", "x")


def test_build_agent_loop_accepts_provider_and_model(monkeypatch):
    import sys, types

    class FakeOpenAI:
        def __init__(self, *a, **k):
            pass

    fake_openai_mod = types.ModuleType("openai")
    fake_openai_mod.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)

    loop = factory.build_agent_loop(provider="LOCAL", model="qwen-32b")
    assert loop.model == "qwen-32b"
    assert loop.registry.get("run_ue_python") is not None


def test_build_agent_loop_still_works_with_explicit_client():
    class Dummy:
        pass
    loop = factory.build_agent_loop(Dummy())
    assert loop.registry.get("run_ue_python") is not None
