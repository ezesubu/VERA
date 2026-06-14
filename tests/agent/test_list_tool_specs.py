"""Tests: list_tool_specs() returns the catalog of available tools for the UI."""
import json

import pytest

import vera.agent.factory as factory
from vera.agent.factory import list_tool_specs


_ENUM_PLUGIN_TOOL = '''
from vera.agent.tool import Tool, ToolResult

class WidgetTool(Tool):
    name = "widget_tool"
    description = "Spawns a widget. Long extra blob that should be cut off."
    input_schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["a", "b", "c"]},
            "count": {"type": "integer"},
        },
        "required": ["kind"],
    }
    def execute(self, args, ctx):
        return ToolResult("ok")
'''


def _make_plugin(root, pid, *, enabled=True, tool_src=_ENUM_PLUGIN_TOOL, display_name=None):
    pdir = root / pid
    (pdir / "tools").mkdir(parents=True)
    man = {
        "name": display_name or pid,
        "version": "1",
        "author": "t",
        "description": "d",
        "enabled": enabled,
    }
    (pdir / "plugin.json").write_text(json.dumps(man), encoding="utf-8")
    (pdir / "tools" / "t.py").write_text(tool_src, encoding="utf-8")


@pytest.fixture
def plugins_dir(tmp_path, monkeypatch):
    d = tmp_path / "VERA_Plugins"
    d.mkdir()
    monkeypatch.setattr(factory, "PLUGINS_DIR", str(d))
    return d


def test_includes_core_tools_with_no_plugin(plugins_dir):
    specs = list_tool_specs()
    by_name = {s["name"]: s for s in specs}
    assert "run_ue_python" in by_name
    assert "inspect_level" in by_name
    assert by_name["run_ue_python"]["plugin"] is None
    assert by_name["inspect_level"]["plugin"] is None


def test_enabled_plugin_tool_with_enum_arg(plugins_dir):
    _make_plugin(plugins_dir, "demo", display_name="Demo Plugin")
    specs = list_tool_specs()
    by_name = {s["name"]: s for s in specs}
    assert "widget_tool" in by_name
    w = by_name["widget_tool"]
    assert w["plugin"] == "Demo Plugin"
    args = {a["name"]: a for a in w["args"]}
    assert args["kind"]["enum"] == ["a", "b", "c"]
    assert args["kind"]["required"] is True
    assert args["count"]["enum"] is None
    assert args["count"]["required"] is False


def test_disabled_plugin_tool_absent(plugins_dir):
    _make_plugin(plugins_dir, "demo", enabled=False)
    specs = list_tool_specs()
    assert "widget_tool" not in {s["name"] for s in specs}


def test_desc_is_first_sentence(plugins_dir):
    _make_plugin(plugins_dir, "demo")
    specs = list_tool_specs()
    w = [s for s in specs if s["name"] == "widget_tool"][0]
    assert w["desc"] == "Spawns a widget."
    assert "blob" not in w["desc"]


def test_result_is_deterministic(plugins_dir):
    _make_plugin(plugins_dir, "demo")
    a = [s["name"] for s in list_tool_specs()]
    b = [s["name"] for s in list_tool_specs()]
    assert a == b
