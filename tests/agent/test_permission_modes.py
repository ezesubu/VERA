"""Modos de permiso: readonly filtra tools destructivas; auto auto-aprueba."""
from tests.agent.fakes import FakeClient, _Resp, _Text, _ToolUse
from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.tool import Tool, ToolResult


class SafeTool(Tool):
    name = "read_thing"
    description = "lee"
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args, ctx):
        return ToolResult("leido")


class DangerTool(Tool):
    name = "delete_thing"
    description = "borra"
    input_schema = {"type": "object", "properties": {}}
    destructive = True

    def execute(self, args, ctx):
        return ToolResult("borrado")


def _reg():
    r = ToolRegistry()
    r.register(SafeTool())
    r.register(DangerTool())
    return r


def test_readonly_hides_destructive_tools_from_model():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    AgentLoop(_reg(), client).run("hola", include_destructive=False)
    sent_tools = client.messages.calls[0]["tools"]
    names = [t["name"] for t in sent_tools]
    assert "read_thing" in names
    assert "delete_thing" not in names


def test_default_includes_destructive_tools():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    AgentLoop(_reg(), client).run("hola")
    names = [t["name"] for t in client.messages.calls[0]["tools"]]
    assert "delete_thing" in names


def test_ask_mode_confirm_can_deny_destructive():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "delete_thing", {})]),
        _Resp("end_turn", [_Text("fin")]),
    ])
    out = AgentLoop(_reg(), client).run("borra", confirm=lambda tool, args: False)
    user_msg = client.messages.calls[1]["messages"][-1]
    result = user_msg["content"][0]
    assert result["is_error"] is True
    assert "rechaz" in result["content"].lower()
    assert out["status"] == "success"


def test_auto_mode_confirm_always_approves():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "delete_thing", {})]),
        _Resp("end_turn", [_Text("fin")]),
    ])
    out = AgentLoop(_reg(), client).run("borra", confirm=lambda tool, args: True)
    user_msg = client.messages.calls[1]["messages"][-1]
    result = user_msg["content"][0]
    assert result["is_error"] is False
    assert "borrado" in result["content"]
    assert out["status"] == "success"
