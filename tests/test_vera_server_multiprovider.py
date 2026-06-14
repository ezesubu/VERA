"""Tests for the extended payload, control ops and permission modes in VeraServer."""
import json
import os
import threading

import pytest

import vera.core.vera_server as vs


def _bare_server():
    """VeraServer without __init__ (no bind/manager): pure methods only."""
    return vs.VeraServer.__new__(vs.VeraServer)


# ---------------- control ops ----------------

def test_control_op_providers():
    srv = _bare_server()
    resp = srv._handle_control_op({"op": "providers"})
    assert resp["type"] == "providers"
    ids = {p["id"] for p in resp["providers"]}
    assert {"ANTHROPIC", "OPENAI", "GEMINI", "LOCAL"} <= ids
    local = [p for p in resp["providers"] if p["id"] == "LOCAL"][0]
    assert local["needs_key"] is False


def test_control_op_list_models_local(monkeypatch):
    srv = _bare_server()
    import vera.agent.models as models
    monkeypatch.setattr(
        models, "list_models",
        lambda provider, http=None: {"provider": provider, "models": ["qwen"], "status": "online"},
    )
    resp = srv._handle_control_op({"op": "list_models", "provider": "LOCAL"})
    assert resp["type"] == "models"
    assert resp["provider"] == "LOCAL"
    assert resp["models"] == ["qwen"]
    assert resp["status"] == "online"


def test_control_op_test_connection_missing_key(monkeypatch):
    srv = _bare_server()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = srv._handle_control_op({"op": "test_connection", "provider": "OPENAI"})
    assert resp["type"] == "conn"
    assert resp["provider"] == "OPENAI"
    assert resp["ok"] is False


def test_control_op_test_connection_local_online(monkeypatch):
    srv = _bare_server()
    import vera.agent.models as models
    monkeypatch.setattr(
        models, "list_models",
        lambda provider, http=None: {"provider": provider, "models": ["qwen"], "status": "online"},
    )
    resp = srv._handle_control_op({"op": "test_connection", "provider": "LOCAL"})
    assert resp["ok"] is True


def test_control_op_cancel_sets_flag():
    srv = _bare_server()
    srv._cancel = threading.Event()
    assert not srv._cancel.is_set()
    resp = srv._handle_control_op({"op": "cancel"})
    assert resp == {"type": "cancelled", "ok": True}
    assert srv._cancel.is_set()


def test_control_op_save_credentials_writes_env(tmp_path, monkeypatch):
    srv = _bare_server()
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=1\n", encoding="utf-8")
    monkeypatch.setattr(srv, "_env_path", lambda: str(env_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resp = srv._handle_control_op({"op": "save_credentials", "provider": "OPENAI", "key": "sk-xyz"})
    assert resp == {"type": "saved", "provider": "OPENAI", "ok": True}
    assert "key" not in resp  # the key is NEVER returned
    content = env_file.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-xyz" in content
    assert "EXISTING=1" in content
    assert os.environ["OPENAI_API_KEY"] == "sk-xyz"


def test_control_op_save_credentials_updates_existing_key(tmp_path, monkeypatch):
    srv = _bare_server()
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=old\nOTHER=2\n", encoding="utf-8")
    monkeypatch.setattr(srv, "_env_path", lambda: str(env_file))

    srv._handle_control_op({"op": "save_credentials", "provider": "OPENAI", "key": "new"})
    content = env_file.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=new" in content
    assert "OPENAI_API_KEY=old" not in content
    assert content.count("OPENAI_API_KEY") == 1
    assert "OTHER=2" in content


def test_control_op_unknown_returns_error():
    srv = _bare_server()
    resp = srv._handle_control_op({"op": "nope"})
    assert resp["type"] == "error"


def test_control_op_commands_returns_catalog(tmp_path, monkeypatch):
    srv = _bare_server()
    _stub_plugins_dir(srv, tmp_path, monkeypatch)
    resp = srv._handle_control_op({"op": "commands"})
    assert resp["type"] == "commands"
    cmds = resp["commands"]
    assert cmds  # non-empty
    by_name = {c["name"]: c for c in cmds}
    # core tools are present with plugin == None
    assert "run_ue_python" in by_name
    assert by_name["run_ue_python"]["plugin"] is None
    # the stubbed enabled plugin's tool is present
    assert "demo_tool" in by_name
    assert by_name["demo_tool"]["plugin"] == "Demo"


# ---------------- per-turn reconfig ----------------

class _FakeLoop:
    def __init__(self):
        self.llm = "old"
        self.model = "old-model"
        self.ran_with = None

    def run(self, command, emit=None, messages=None, confirm=None, include_destructive=True):
        self.ran_with = {
            "command": command,
            "include_destructive": include_destructive,
            "model": self.model,
            "llm": self.llm,
        }
        if emit:
            emit({"type": "final", "status": "success", "msg": "ok"})
        return {"status": "success", "msg": "ok"}


class _FakeSession:
    def __init__(self, loop):
        self.loop = loop

    def run(self, command, emit=None, confirm=None, include_destructive=True):
        return self.loop.run(command, emit=emit, confirm=confirm,
                             include_destructive=include_destructive)


def test_reconfigures_loop_provider_and_model(monkeypatch):
    srv = _bare_server()
    loop = _FakeLoop()
    srv._sessions = {"default": {"session": _FakeSession(loop), "compact": False}}

    import vera.core.vera_server as mod
    monkeypatch.setattr(mod, "make_llm_client",
                        lambda provider, model: f"client:{provider}:{model}")

    srv._reconfigure_session("default", "OPENAI", "gpt-4o")
    assert loop.llm == "client:OPENAI:gpt-4o"
    assert loop.model == "gpt-4o"


def test_mode_to_run_kwargs():
    srv = _bare_server()
    # ask: normal confirm gate, destructive ops visible
    assert srv._include_destructive_for_mode("ask") is True
    assert srv._include_destructive_for_mode("auto") is True
    assert srv._include_destructive_for_mode("readonly") is False


# ---------------- plugins control ops ----------------

import json as _json


def _stub_plugins_dir(srv, tmp_path, monkeypatch):
    """Point the server's plugins dir at a temp dir with one example plugin."""
    import vera.agent.factory as factory
    pdir = tmp_path / "VERA_Plugins" / "demo"
    (pdir / "tools").mkdir(parents=True)
    man = {"name": "Demo", "version": "2.0", "author": "me", "description": "x", "enabled": True}
    (pdir / "plugin.json").write_text(_json.dumps(man), encoding="utf-8")
    (pdir / "tools" / "t.py").write_text(
        "from vera.agent.tool import Tool, ToolResult\n"
        "class DemoTool(Tool):\n"
        "    name='demo_tool'\n"
        "    description='d'\n"
        "    input_schema={'type':'object','properties':{}}\n"
        "    def execute(self, args, ctx):\n"
        "        return ToolResult('ok')\n",
        encoding="utf-8",
    )
    (pdir / "SKILL.md").write_text("be nice", encoding="utf-8")
    monkeypatch.setattr(factory, "PLUGINS_DIR", str(tmp_path / "VERA_Plugins"))
    return str(tmp_path / "VERA_Plugins")


def test_control_op_plugins_lists(tmp_path, monkeypatch):
    srv = _bare_server()
    _stub_plugins_dir(srv, tmp_path, monkeypatch)
    resp = srv._handle_control_op({"op": "plugins"})
    assert resp["type"] == "plugins"
    p = [x for x in resp["plugins"] if x["id"] == "demo"][0]
    assert p["name"] == "Demo"
    assert p["version"] == "2.0"
    assert p["author"] == "me"
    assert p["enabled"] is True
    assert "demo_tool" in p["tools"]
    assert p["has_skill"] is True


def test_control_op_set_plugin_persists(tmp_path, monkeypatch):
    srv = _bare_server()
    _stub_plugins_dir(srv, tmp_path, monkeypatch)
    resp = srv._handle_control_op({"op": "set_plugin", "id": "demo", "enabled": False})
    assert resp == {"type": "plugin_set", "id": "demo", "enabled": False, "ok": True}
    # next plugins listing reflects it
    listing = srv._handle_control_op({"op": "plugins"})
    demo = [x for x in listing["plugins"] if x["id"] == "demo"][0]
    assert demo["enabled"] is False


def test_control_op_set_plugin_unknown(tmp_path, monkeypatch):
    srv = _bare_server()
    _stub_plugins_dir(srv, tmp_path, monkeypatch)
    resp = srv._handle_control_op({"op": "set_plugin", "id": "ghost", "enabled": False})
    assert resp["type"] == "plugin_set"
    assert resp["ok"] is False


def test_set_plugin_clears_session_so_next_turn_rebuilds(tmp_path, monkeypatch):
    srv = _bare_server()
    _stub_plugins_dir(srv, tmp_path, monkeypatch)
    srv._sessions = {"default": object()}  # pretend a session exists
    srv._handle_control_op({"op": "set_plugin", "id": "demo", "enabled": False})
    assert srv._sessions == {}  # all tabs rebuild on their next command


def _stub_session_builders(monkeypatch):
    """Stub build_agent_loop + AgentSession so _agent_session needs no real LLM.
    The fake session just carries the compact flag it was built with."""
    import vera.agent.factory as factory
    import vera.agent.session as session_mod

    class _FakeSess:
        def __init__(self, loop):
            self.loop = loop

    monkeypatch.setattr(session_mod, "AgentSession", _FakeSess)
    monkeypatch.setattr(factory, "build_agent_loop", lambda **kw: kw.get("compact"))


def test_compact_flag_rebuilds_session_when_changed(monkeypatch):
    srv = _bare_server()
    srv._sessions = {}
    _stub_session_builders(monkeypatch)
    s1 = srv._agent_session("default", compact=False)
    s2 = srv._agent_session("default", compact=False)
    assert s1 is s2                       # same compact → reused (history preserved)
    s3 = srv._agent_session("default", compact=True)
    assert s3 is not s1                   # compact changed → rebuilt


def test_compact_flag_no_rebuild_when_unchanged(monkeypatch):
    srv = _bare_server()
    srv._sessions = {}
    _stub_session_builders(monkeypatch)
    s1 = srv._agent_session("default", compact=True)
    s2 = srv._agent_session("default", compact=True)
    assert s1 is s2


def test_separate_sessions_per_tab(monkeypatch):
    srv = _bare_server()
    srv._sessions = {}
    _stub_session_builders(monkeypatch)
    a = srv._agent_session("tab-a", compact=False)
    b = srv._agent_session("tab-b", compact=False)
    assert a is not b                     # each tab keeps its own context
    assert srv._agent_session("tab-a", compact=False) is a
