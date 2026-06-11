from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.tool import Tool, ToolResult, image_block


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


def test_stop_reason_max_tokens_corta_limpio():
    """max_tokens sin tool_use no debe appendear un user vacío (400 de la API)."""
    client = FakeClient([_Resp("max_tokens", [_Text("respuesta trunca")])])
    out = AgentLoop(_reg(), client).run("hola")
    assert out["status"] == "error"
    assert "max_tokens" in out["msg"]
    # una sola llamada: el loop NO debe reintentar con un mensaje malformado
    assert len(client.messages.calls) == 1


def test_stop_reason_refusal_corta_limpio():
    client = FakeClient([_Resp("refusal", [])])
    events = []
    out = AgentLoop(_reg(), client).run("hola", emit=events.append)
    assert out["status"] == "error"
    assert "refusal" in out["msg"]
    assert events[-1]["type"] == "final"
    assert events[-1]["status"] == "error"


def test_tool_use_sin_bloques_corta_limpio():
    """stop_reason tool_use con content sin bloques tool_use no debe appendear content:[]."""
    client = FakeClient([_Resp("tool_use", [_Text("solo texto")])])
    out = AgentLoop(_reg(), client).run("hola")
    assert out["status"] == "error"
    assert len(client.messages.calls) == 1


def test_stop_reason_stop_sequence_corta_limpio():
    client = FakeClient([_Resp("stop_sequence", [_Text("cortado")])])
    out = AgentLoop(_reg(), client).run("hola")
    assert out["status"] == "error"
    assert "stop_sequence" in out["msg"]
    assert len(client.messages.calls) == 1


def test_tool_result_con_blocks_pasa_intacto():
    class CameraTool(Tool):
        name = "camera"
        description = "c"
        input_schema = {"type": "object", "properties": {}}
        destructive = False

        def execute(self, args, ctx):
            return ToolResult([image_block("QUJD")])

    reg = ToolRegistry()
    reg.register(CameraTool())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "camera", {})]),
        _Resp("end_turn", [_Text("vi la imagen")]),
    ])
    AgentLoop(reg, client).run("sacá una foto")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert isinstance(tr["content"], list)
    assert tr["content"][0]["type"] == "image"


def test_tool_result_largo_se_trunca():
    class VerboseTool(Tool):
        name = "verbose"
        description = "v"
        input_schema = {"type": "object", "properties": {}}
        destructive = False

        def execute(self, args, ctx):
            return ToolResult("x" * 50_000)

    reg = ToolRegistry()
    reg.register(VerboseTool())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "verbose", {})]),
        _Resp("end_turn", [_Text("ok")]),
    ])
    AgentLoop(reg, client).run("dale")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert len(tr["content"]) < 50_000
    assert "truncado" in tr["content"]
