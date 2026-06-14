"""Tests for the studio plugin loader (vera/agent/plugins.py)."""
import json

import pytest

from vera.agent import plugins as plug
from vera.agent.tool import Tool


# ---------------- helpers ----------------

def _write_plugin(root, pid, *, manifest=None, tool_src=None, skill=None):
    pdir = root / pid
    pdir.mkdir(parents=True)
    man = {"name": pid, "version": "1.0.0", "author": "t", "description": "d", "enabled": True}
    if manifest is not None:
        man.update(manifest)
    (pdir / "plugin.json").write_text(json.dumps(man), encoding="utf-8")
    if tool_src is not None:
        tdir = pdir / "tools"
        tdir.mkdir()
        (tdir / "mytool.py").write_text(tool_src, encoding="utf-8")
    if skill is not None:
        (pdir / "SKILL.md").write_text(skill, encoding="utf-8")
    return pdir


_GOOD_TOOL = '''
from vera.agent.tool import Tool, ToolResult

class GreetTool(Tool):
    name = "greet_xyz"
    description = "greets"
    input_schema = {"type": "object", "properties": {}}
    def execute(self, args, ctx):
        return ToolResult("hi")
'''


# ---------------- discovery ----------------

def test_missing_dir_returns_empty(tmp_path):
    assert plug.discover_plugins(str(tmp_path / "nope")) == []


def test_discovers_valid_plugin(tmp_path):
    _write_plugin(tmp_path, "alpha", tool_src=_GOOD_TOOL, skill="# Skill\nbe nice")
    found = plug.discover_plugins(str(tmp_path))
    assert len(found) == 1
    p = found[0]
    assert p.id == "alpha"
    assert p.name == "alpha"
    assert p.version == "1.0.0"
    assert p.enabled is True
    assert len(p.tool_classes) == 1
    assert issubclass(p.tool_classes[0], Tool)
    assert p.tool_classes[0].name == "greet_xyz"
    assert "be nice" in p.skill_text


def test_plugin_without_tools_or_skill(tmp_path):
    _write_plugin(tmp_path, "bare")
    found = plug.discover_plugins(str(tmp_path))
    assert len(found) == 1
    assert found[0].tool_classes == []
    assert found[0].skill_text is None


def test_broken_plugin_is_skipped_not_fatal(tmp_path):
    _write_plugin(tmp_path, "good", tool_src=_GOOD_TOOL)
    # broken: tool file with a syntax error
    _write_plugin(tmp_path, "broken", tool_src="this is not valid python !!!")
    # broken manifest: invalid json
    bad = tmp_path / "badjson"
    bad.mkdir()
    (bad / "plugin.json").write_text("{ not json", encoding="utf-8")

    found = plug.discover_plugins(str(tmp_path))
    ids = {p.id for p in found}
    assert "good" in ids
    # broken-tool plugin still discovered but with no tool classes loaded
    broken = [p for p in found if p.id == "broken"][0]
    assert broken.tool_classes == []
    # badjson is skipped entirely (no usable manifest)
    assert "badjson" not in ids


def test_non_directory_entries_ignored(tmp_path):
    (tmp_path / "loose.txt").write_text("x", encoding="utf-8")
    _write_plugin(tmp_path, "alpha")
    found = plug.discover_plugins(str(tmp_path))
    assert {p.id for p in found} == {"alpha"}


# ---------------- enable / disable persistence ----------------

def test_manifest_enabled_false_respected(tmp_path):
    _write_plugin(tmp_path, "alpha", manifest={"enabled": False})
    p = plug.discover_plugins(str(tmp_path))[0]
    assert p.enabled is False


def test_set_enabled_persists_to_manifest(tmp_path):
    _write_plugin(tmp_path, "alpha")
    plug.set_plugin_enabled(str(tmp_path), "alpha", False)
    # re-discover: state survives
    p = plug.discover_plugins(str(tmp_path))[0]
    assert p.enabled is False
    # and the manifest on disk carries the field
    man = json.loads((tmp_path / "alpha" / "plugin.json").read_text(encoding="utf-8"))
    assert man["enabled"] is False
    # re-enable
    plug.set_plugin_enabled(str(tmp_path), "alpha", True)
    assert plug.discover_plugins(str(tmp_path))[0].enabled is True


def test_set_enabled_unknown_plugin_returns_false(tmp_path):
    _write_plugin(tmp_path, "alpha")
    assert plug.set_plugin_enabled(str(tmp_path), "ghost", False) is False


# ---------------- per-plugin pip deps ----------------

def test_deps_parsed_from_manifest(tmp_path):
    _write_plugin(tmp_path, "heavy",
                  manifest={"deps": ["pyautogui>=0.9.54", "Pillow>=10.0.0"],
                            "deps_import": "pyautogui"})
    p = plug.discover_plugins(str(tmp_path))[0]
    assert p.deps == ["pyautogui>=0.9.54", "Pillow>=10.0.0"]
    assert p.deps_import == "pyautogui"


def test_deps_default_empty_and_bad_type_ignored(tmp_path):
    _write_plugin(tmp_path, "a")                          # no deps key
    _write_plugin(tmp_path, "b", manifest={"deps": "notalist"})
    by_id = {p.id: p for p in plug.discover_plugins(str(tmp_path))}
    assert by_id["a"].deps == [] and by_id["a"].deps_import is None
    assert by_id["b"].deps == []


def test_plugin_missing_deps_present_vs_absent(tmp_path):
    # deps_import resolvable (stdlib) → nothing missing
    _write_plugin(tmp_path, "present",
                  manifest={"deps": ["something>=1"], "deps_import": "json"})
    # deps_import not importable → returns the requirements
    _write_plugin(tmp_path, "absent",
                  manifest={"deps": ["ghostpkg>=1"], "deps_import": "no_such_module_xyz"})
    by_id = {p.id: p for p in plug.discover_plugins(str(tmp_path))}
    assert plug.plugin_missing_deps(by_id["present"]) == []
    assert plug.plugin_missing_deps(by_id["absent"]) == ["ghostpkg>=1"]


def test_install_packages_builds_pip_command_and_succeeds(tmp_path):
    calls = []
    ok = plug.install_packages(["pyautogui>=0.9.54"], str(tmp_path),
                               python="py", runner=lambda cmd: calls.append(cmd))
    assert ok is True
    assert calls and calls[0][:5] == ["py", "-m", "pip", "install", "--target"]
    assert "pyautogui>=0.9.54" in calls[0]


def test_install_packages_empty_is_noop():
    assert plug.install_packages([], "/tmp/whatever") is True


def test_install_packages_failure_returns_false(tmp_path):
    def boom(cmd):
        raise RuntimeError("pip exploded")
    assert plug.install_packages(["x"], str(tmp_path), python="py", runner=boom) is False
