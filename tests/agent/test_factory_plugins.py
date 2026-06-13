"""Tests: factory injects plugin tools/skills and honors the compact prompt."""
import json

import pytest

import vera.agent.factory as factory
from vera.agent.factory import build_agent_loop, COMPACT_SYSTEM_PROMPT, SYSTEM_PROMPT


class _DummyLLM:
    pass


_PLUGIN_TOOL = '''
from vera.agent.tool import Tool, ToolResult

class PluginThing(Tool):
    name = "plugin_thing"
    description = "does a plugin thing"
    input_schema = {"type": "object", "properties": {}}
    def execute(self, args, ctx):
        return ToolResult("ok")
'''


def _make_plugin(root, pid, *, enabled=True, with_tool=True, skill=None):
    pdir = root / pid
    (pdir / "tools").mkdir(parents=True) if with_tool else pdir.mkdir(parents=True)
    man = {"name": pid, "version": "1", "author": "t", "description": "d", "enabled": enabled}
    (pdir / "plugin.json").write_text(json.dumps(man), encoding="utf-8")
    if with_tool:
        (pdir / "tools" / "t.py").write_text(_PLUGIN_TOOL, encoding="utf-8")
    if skill:
        (pdir / "SKILL.md").write_text(skill, encoding="utf-8")


@pytest.fixture
def plugins_dir(tmp_path, monkeypatch):
    d = tmp_path / "VERA_Plugins"
    d.mkdir()
    monkeypatch.setattr(factory, "PLUGINS_DIR", str(d))
    return d


def test_enabled_plugin_tools_and_skill_injected(plugins_dir):
    _make_plugin(plugins_dir, "p1", skill="Always greet first.")
    loop = build_agent_loop(llm_client=_DummyLLM())
    # plugin tool is registered alongside core tools
    assert loop.registry.get("plugin_thing") is not None
    assert loop.registry.get("run_ue_python") is not None
    # skill text is appended to the system prompt
    assert "Always greet first." in loop.system
    assert "Studio plugins" in loop.system


def test_disabled_plugin_is_excluded(plugins_dir):
    _make_plugin(plugins_dir, "p1", enabled=False, skill="Never run me.")
    loop = build_agent_loop(llm_client=_DummyLLM())
    assert loop.registry.get("plugin_thing") is None
    assert "Never run me." not in loop.system


def test_compact_prompt_used_when_compact_true(plugins_dir):
    loop = build_agent_loop(llm_client=_DummyLLM(), compact=True)
    assert loop.system.startswith(COMPACT_SYSTEM_PROMPT)
    assert COMPACT_SYSTEM_PROMPT != SYSTEM_PROMPT
    assert len(COMPACT_SYSTEM_PROMPT) < len(SYSTEM_PROMPT)


def test_compact_prompt_still_appends_plugin_skills(plugins_dir):
    _make_plugin(plugins_dir, "p1", with_tool=False, skill="Compact skill rule.")
    loop = build_agent_loop(llm_client=_DummyLLM(), compact=True)
    assert loop.system.startswith(COMPACT_SYSTEM_PROMPT)
    assert "Compact skill rule." in loop.system


def test_full_prompt_by_default(plugins_dir):
    loop = build_agent_loop(llm_client=_DummyLLM())
    assert loop.system.startswith(SYSTEM_PROMPT)
