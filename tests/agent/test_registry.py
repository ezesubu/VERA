import pytest

from vera.agent.tool import Tool, ToolResult
from vera.agent.registry import ToolRegistry


class FakeTool(Tool):
    name = "fake"
    description = "a fake tool"
    input_schema = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        return ToolResult("ok")


def test_register_and_get():
    reg = ToolRegistry()
    t = FakeTool()
    reg.register(t)
    assert reg.get("fake") is t
    assert reg.all() == [t]


def test_get_missing_returns_none():
    assert ToolRegistry().get("nope") is None


def test_register_duplicate_raises():
    reg = ToolRegistry()
    reg.register(FakeTool())
    with pytest.raises(ValueError):
        reg.register(FakeTool())


def test_to_anthropic_shape():
    reg = ToolRegistry()
    reg.register(FakeTool())
    assert reg.to_anthropic() == [
        {
            "name": "fake",
            "description": "a fake tool",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]


class WordyTool(Tool):
    name = "wordy"
    description = (
        "Spawns an actor in the level. Use this when the user asks to place "
        "something. It supports many actor classes and locations."
    )
    input_schema = {"type": "object", "properties": {"x": {"type": "number"}}}

    def execute(self, args, ctx):
        return ToolResult("ok")


def test_to_anthropic_default_keeps_full_description():
    reg = ToolRegistry()
    reg.register(WordyTool())
    out = reg.to_anthropic()
    assert out[0]["description"] == WordyTool.description


def test_to_anthropic_compact_trims_to_first_sentence():
    reg = ToolRegistry()
    reg.register(WordyTool())
    out = reg.to_anthropic(compact=True)
    # first sentence only, period kept, nothing after it
    assert out[0]["description"] == "Spawns an actor in the level."
    # name + schema untouched
    assert out[0]["name"] == "wordy"
    assert out[0]["input_schema"] == {
        "type": "object",
        "properties": {"x": {"type": "number"}},
    }


def test_to_anthropic_compact_no_sentence_break_falls_back_to_word_boundary():
    class NoBreakTool(Tool):
        name = "nobreak"
        description = "x" * 300  # no ". " anywhere
        input_schema = {"type": "object", "properties": {}}

        def execute(self, args, ctx):
            return ToolResult("ok")

    reg = ToolRegistry()
    reg.register(NoBreakTool())
    out = reg.to_anthropic(compact=True)
    assert len(out[0]["description"]) <= 145
    assert out[0]["name"] == "nobreak"


def test_to_anthropic_compact_short_description_unchanged():
    reg = ToolRegistry()
    reg.register(FakeTool())  # "a fake tool" — no sentence break, short
    out = reg.to_anthropic(compact=True)
    assert out[0]["description"] == "a fake tool"


def test_discover_finds_run_ue_python():
    import vera.agent.tools as tools_pkg

    reg = ToolRegistry()
    reg.discover(tools_pkg)
    tool = reg.get("run_ue_python")
    assert tool is not None
    assert tool.destructive is True


def test_discover_classes_registers_loaded_classes():
    reg = ToolRegistry()
    reg.discover_classes([FakeTool])
    assert reg.get("fake") is not None


def test_discover_classes_skips_non_tool_and_base():
    reg = ToolRegistry()
    # passing the base Tool class or a non-Tool is ignored, not an error
    reg.discover_classes([Tool, int, FakeTool])
    assert reg.get("fake") is not None
    assert reg.all() == [reg.get("fake")]
