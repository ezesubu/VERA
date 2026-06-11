import pytest

from vera.agent.tool import Tool, ToolResult
from vera.agent.registry import ToolRegistry


class FakeTool(Tool):
    name = "fake"
    description = "una tool fake"
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
            "description": "una tool fake",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]


def test_discover_finds_run_ue_python():
    import vera.agent.tools as tools_pkg

    reg = ToolRegistry()
    reg.discover(tools_pkg)
    tool = reg.get("run_ue_python")
    assert tool is not None
    assert tool.destructive is True
