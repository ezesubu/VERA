"""Tests for make_llm_client per provider and build_agent_loop with provider/model."""
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
    # LOCAL needs no key or network: the OpenAICompatClient is built with a real
    # openai client only in production, but here we inject via an openai mock.
    import vera.llm.openai_compat_client as occ

    class FakeOpenAI:
        def __init__(self, *a, **k):
            self.kwargs = k

    # openai is not installed in CI → patch the import inside the client
    import sys, types
    fake_openai_mod = types.ModuleType("openai")
    fake_openai_mod.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)
    monkeypatch.setenv("VERA_LOCAL_BASE_URL", "http://localhost:1234/v1")

    client = factory.make_llm_client("LOCAL", "qwen-32b")
    assert isinstance(client, occ.OpenAICompatClient)
    assert client.model == "qwen-32b"
    assert client.base_url == "http://localhost:1234/v1"


def test_make_llm_client_local_unconfigured_raises(monkeypatch):
    monkeypatch.delenv("VERA_LOCAL_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        factory.make_llm_client("LOCAL", "qwen-32b")


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
    monkeypatch.setenv("VERA_LOCAL_BASE_URL", "http://localhost:1234/v1")

    loop = factory.build_agent_loop(provider="LOCAL", model="qwen-32b")
    assert loop.model == "qwen-32b"
    assert loop.registry.get("run_ue_python") is not None


def test_build_agent_loop_still_works_with_explicit_client():
    class Dummy:
        pass
    loop = factory.build_agent_loop(Dummy())
    assert loop.registry.get("run_ue_python") is not None
