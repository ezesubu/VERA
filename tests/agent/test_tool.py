from vera.agent.tool import Tool, ToolResult, ToolContext, image_block


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


def test_image_block_forma_de_la_api():
    b = image_block("QUJD", media_type="image/jpeg")
    assert b == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }


def test_tool_result_acepta_lista_de_blocks():
    blocks = [image_block("QUJD"), {"type": "text", "text": "screenshot del viewport"}]
    r = ToolResult(blocks)
    assert r.content is blocks
    assert r.is_error is False
