from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.tool import Tool, ToolResult


# --- fakes que imitan la forma del SDK de Anthropic ---
class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUse:
    type = "tool_use"

    def __init__(self, id, name, input):
        self.id = id
        self.name = name
        self.input = input


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)


class FakeClient:
    def __init__(self, scripted):
        self.messages = _FakeMessages(scripted)


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args, ctx):
        return ToolResult(f"echo:{args.get('x')}")


def _reg():
    r = ToolRegistry()
    r.register(EchoTool())
    return r


def test_end_turn_immediately():
    client = FakeClient([_Resp("end_turn", [_Text("listo")])])
    out = AgentLoop(_reg(), client).run("hola")
    assert out == {"status": "success", "msg": "listo"}


def test_tool_use_then_end():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "echo", {"x": 5})]),
        _Resp("end_turn", [_Text("hecho")]),
    ])
    out = AgentLoop(_reg(), client).run("usá echo")
    assert out["status"] == "success"
    assert out["msg"] == "hecho"
    user_msg = client.messages.calls[1]["messages"][-1]
    assert user_msg["role"] == "user"
    assert user_msg["content"][0]["type"] == "tool_result"
    assert "echo:5" in user_msg["content"][0]["content"]


def test_unknown_tool_reports_error():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "nope", {})]),
        _Resp("end_turn", [_Text("fin")]),
    ])
    AgentLoop(_reg(), client).run("x")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True
    assert "nope" in tr["content"]


def test_destructive_confirm_reject():
    class Danger(Tool):
        name = "danger"
        description = "d"
        input_schema = {"type": "object", "properties": {}}
        destructive = True

        def execute(self, args, ctx):
            raise AssertionError("no debe ejecutarse")

    reg = ToolRegistry()
    reg.register(Danger())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "danger", {})]),
        _Resp("end_turn", [_Text("fin")]),
    ])
    AgentLoop(reg, client, confirm=lambda tool, args: False).run("borrá todo")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True
    assert "rechaz" in tr["content"].lower()


def test_emit_events():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "echo", {"x": 1})]),
        _Resp("end_turn", [_Text("ok")]),
    ])
    events = []
    AgentLoop(_reg(), client).run("x", emit=events.append)
    types = [e["type"] for e in events]
    assert "tool_use" in types
    assert "tool_result" in types
    assert "final" in types
