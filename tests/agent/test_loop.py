from tests.agent.fakes import FakeClient, _Resp, _Text, _ToolUse, thinking_event
from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.tool import Tool, ToolResult, image_block


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
    client = FakeClient([_Resp("end_turn", [_Text("done")])])
    out = AgentLoop(_reg(), client).run("hi")
    assert out == {"status": "success", "msg": "done"}


def test_tool_use_then_end():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "echo", {"x": 5})]),
        _Resp("end_turn", [_Text("done")]),
    ])
    out = AgentLoop(_reg(), client).run("use echo")
    assert out["status"] == "success"
    assert out["msg"] == "done"
    user_msg = client.messages.calls[1]["messages"][-1]
    assert user_msg["role"] == "user"
    assert user_msg["content"][0]["type"] == "tool_result"
    assert "echo:5" in user_msg["content"][0]["content"]


def test_unknown_tool_reports_error():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "nope", {})]),
        _Resp("end_turn", [_Text("done")]),
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
            raise AssertionError("must not run")

    reg = ToolRegistry()
    reg.register(Danger())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "danger", {})]),
        _Resp("end_turn", [_Text("done")]),
    ])
    AgentLoop(reg, client, confirm=lambda tool, args: False).run("delete everything")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True
    assert "reject" in tr["content"].lower()


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


def test_stop_reason_max_tokens_cuts_clean():
    """max_tokens with no tool_use must not append an empty user (API 400)."""
    client = FakeClient([_Resp("max_tokens", [_Text("truncated response")])])
    out = AgentLoop(_reg(), client).run("hi")
    assert out["status"] == "error"
    assert "max_tokens" in out["msg"]
    # a single call: the loop must NOT retry with a malformed message
    assert len(client.messages.calls) == 1


def test_stop_reason_refusal_cuts_clean():
    client = FakeClient([_Resp("refusal", [])])
    events = []
    out = AgentLoop(_reg(), client).run("hi", emit=events.append)
    assert out["status"] == "error"
    assert "refusal" in out["msg"]
    assert events[-1]["type"] == "final"
    assert events[-1]["status"] == "error"


def test_tool_use_with_no_blocks_cuts_clean():
    """stop_reason tool_use whose content has no tool_use blocks must not append content:[]."""
    client = FakeClient([_Resp("tool_use", [_Text("text only")])])
    out = AgentLoop(_reg(), client).run("hi")
    assert out["status"] == "error"
    assert len(client.messages.calls) == 1


def test_stop_reason_stop_sequence_cuts_clean():
    client = FakeClient([_Resp("stop_sequence", [_Text("cut")])])
    out = AgentLoop(_reg(), client).run("hi")
    assert out["status"] == "error"
    assert "stop_sequence" in out["msg"]
    assert len(client.messages.calls) == 1


def test_tool_result_with_blocks_passes_through_intact():
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
        _Resp("end_turn", [_Text("I saw the image")]),
    ])
    AgentLoop(reg, client).run("take a photo")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert isinstance(tr["content"], list)
    assert tr["content"][0]["type"] == "image"


def test_long_tool_result_is_truncated():
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
    AgentLoop(reg, client).run("go")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert len(tr["content"]) < 50_000
    assert "truncated" in tr["content"]


def test_tool_result_exactly_at_limit_is_not_truncated():
    from vera.agent.loop import MAX_TOOL_RESULT_CHARS

    class AtLimitTool(Tool):
        name = "atlimit"
        description = "a"
        input_schema = {"type": "object", "properties": {}}
        destructive = False

        def execute(self, args, ctx):
            return ToolResult("x" * MAX_TOOL_RESULT_CHARS)

    reg = ToolRegistry()
    reg.register(AtLimitTool())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "atlimit", {})]),
        _Resp("end_turn", [_Text("ok")]),
    ])
    AgentLoop(reg, client).run("go")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert len(tr["content"]) == MAX_TOOL_RESULT_CHARS
    assert "truncated" not in tr["content"]


def test_truncated_tool_result_respects_the_strict_limit():
    from vera.agent.loop import MAX_TOOL_RESULT_CHARS

    class HugeTool(Tool):
        name = "huge"
        description = "h"
        input_schema = {"type": "object", "properties": {}}
        destructive = False

        def execute(self, args, ctx):
            return ToolResult("x" * 1_000_000)

    reg = ToolRegistry()
    reg.register(HugeTool())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "huge", {})]),
        _Resp("end_turn", [_Text("ok")]),
    ])
    AgentLoop(reg, client).run("go")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert len(tr["content"]) <= MAX_TOOL_RESULT_CHARS
    assert "truncated" in tr["content"]


def test_streaming_emits_thinking_to_the_timeline():
    client = FakeClient([
        (_Resp("end_turn", [_Text("done")]), [thinking_event("first I look at the level...")]),
    ])
    events = []
    AgentLoop(_reg(), client).run("x", emit=events.append)
    assert {"type": "thinking", "msg": "first I look at the level..."} in events


def test_request_asks_for_thinking_summarized():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    AgentLoop(_reg(), client).run("x")
    kwargs = client.messages.calls[0]
    assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_sdk_exception_closes_the_contract():
    """An SDK exception (timeout, rate limit) must emit final and return error."""

    class _ExplodingMessages:
        def stream(self, **kwargs):
            raise RuntimeError("connection dropped")

    class _ExplodingClient:
        messages = _ExplodingMessages()

    events = []
    out = AgentLoop(_reg(), _ExplodingClient()).run("hi", emit=events.append)
    assert out["status"] == "error"
    assert "connection dropped" in out["msg"]
    assert events[-1]["type"] == "final"
    assert events[-1]["status"] == "error"


class WordyEchoTool(Tool):
    name = "wordy_echo"
    description = "Echoes the input back. Use only when you really need to test echoing."
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args, ctx):
        return ToolResult("ok")


def test_compact_loop_passes_trimmed_tool_descriptions():
    reg = ToolRegistry()
    reg.register(WordyEchoTool())
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    AgentLoop(reg, client, compact=True).run("x")
    tools = client.messages.calls[0]["tools"]
    assert tools[0]["description"] == "Echoes the input back."


def test_default_loop_passes_full_tool_descriptions():
    reg = ToolRegistry()
    reg.register(WordyEchoTool())
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    AgentLoop(reg, client).run("x")
    tools = client.messages.calls[0]["tools"]
    assert tools[0]["description"] == WordyEchoTool.description


def test_should_stop_cuts_the_loop_early():
    """A client that always returns tool_use would reach MAX_ITERATIONS; with
    should_stop returning True after the first call the loop cuts clean."""
    from vera.agent.loop import MAX_ITERATIONS

    # Many more tool_use responses than iterations, to tell a cut from exhaustion.
    client = FakeClient([
        _Resp("tool_use", [_ToolUse(f"t{i}", "echo", {"x": i})])
        for i in range(MAX_ITERATIONS + 5)
    ])
    calls = {"n": 0}

    def should_stop():
        # Allow the first model call; cut from then on.
        calls["n"] += 1
        return calls["n"] > 1

    events = []
    out = AgentLoop(_reg(), client).run(
        "infinite loop", emit=events.append, should_stop=should_stop)
    assert out == {"status": "stopped", "msg": "stopped by user"}
    assert events[-1]["type"] == "final"
    assert events[-1]["status"] == "stopped"
    # Cut early: well below MAX_ITERATIONS.
    assert len(client.messages.calls) < MAX_ITERATIONS


def test_should_stop_before_the_first_call_never_calls_the_model():
    """should_stop True from the start cuts without ever calling the model."""
    client = FakeClient([_Resp("tool_use", [_ToolUse("t1", "echo", {"x": 1})])])
    out = AgentLoop(_reg(), client).run("x", should_stop=lambda: True)
    assert out["status"] == "stopped"
    assert len(client.messages.calls) == 0


def test_should_stop_none_runs_normally():
    """should_stop None (default) does not change the behavior."""
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "echo", {"x": 1})]),
        _Resp("end_turn", [_Text("ok")]),
    ])
    out = AgentLoop(_reg(), client).run("x", should_stop=None)
    assert out["status"] == "success"
    assert out["msg"] == "ok"


def test_image_appends_text_plus_image_block_list():
    """With image, the first user turn is a list of content blocks
    (text + image) so a vision-capable model SEES it."""
    client = FakeClient([_Resp("end_turn", [_Text("I see the image")])])
    img = {"data": "QUJD", "media_type": "image/png"}
    AgentLoop(_reg(), client).run("describe this", image=img)
    user_msg = client.messages.calls[0]["messages"][0]
    assert user_msg["role"] == "user"
    content = user_msg["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "describe this"}
    assert content[1]["type"] == "image"
    assert content[1]["source"] == {
        "type": "base64", "media_type": "image/png", "data": "QUJD"}


def test_no_image_keeps_plain_string_content():
    """Without image, the user turn stays the plain string as always."""
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    AgentLoop(_reg(), client).run("hi")
    user_msg = client.messages.calls[0]["messages"][0]
    assert user_msg == {"role": "user", "content": "hi"}


def test_image_jpeg_media_type_passes_through():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    img = {"data": "Zm9v", "media_type": "image/jpeg"}
    AgentLoop(_reg(), client).run("look", image=img)
    content = client.messages.calls[0]["messages"][0]["content"]
    assert content[1]["source"]["media_type"] == "image/jpeg"


def test_empty_thinking_is_not_emitted():
    """A thinking delta with an empty string must not generate an event (display omitted)."""
    client = FakeClient([
        (_Resp("end_turn", [_Text("done")]), [thinking_event("")]),
    ])
    events = []
    AgentLoop(_reg(), client).run("x", emit=events.append)
    assert [e for e in events if e.get("type") == "thinking"] == []
