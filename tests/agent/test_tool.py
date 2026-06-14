from vera.agent.tool import Tool, ToolResult, ToolContext, image_block


def test_toolresult_defaults():
    r = ToolResult("hi")
    assert r.content == "hi"
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
    ctx.report("A", "msg")  # must not raise an exception


def test_image_block_api_shape():
    b = image_block("QUJD", media_type="image/jpeg")
    assert b == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }


def test_tool_result_accepts_list_of_blocks():
    blocks = [image_block("QUJD"), {"type": "text", "text": "viewport screenshot"}]
    r = ToolResult(blocks)
    assert r.content is blocks
    assert r.is_error is False
