from vera.agent.tool import Tool, ToolResult, ToolContext


def test_toolresult_defaults():
    r = ToolResult("hola")
    assert r.content == "hola"
    assert r.is_error is False


def test_tool_to_anthropic_schema():
    class Dummy(Tool):
        name = "dummy"
        description = "desc"
        input_schema = {"type": "object", "properties": {}}

    t = Dummy()
    assert t.to_anthropic() == {
        "name": "dummy",
        "description": "desc",
        "input_schema": {"type": "object", "properties": {}},
    }
    assert t.destructive is False  # default


def test_toolcontext_report_emits():
    seen = []
    ctx = ToolContext(emit=seen.append)
    ctx.report("A", "msg")
    assert seen == [{"type": "progress", "agent": "A", "msg": "msg"}]


def test_toolcontext_report_noop_without_emit():
    ctx = ToolContext()
    ctx.report("A", "msg")  # no debe lanzar excepción
