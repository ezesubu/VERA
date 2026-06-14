"""Studio plugin loader.

A plugin is a FOLDER inside a `VERA_Plugins/` directory:

    my-plugin/
      plugin.json     -> {"name","version","author","description","enabled":true}
      tools/*.py      -> files with Tool subclasses (optional)
      SKILL.md        -> conventions/instructions in markdown (optional)

`discover_plugins(plugins_dir)` returns a list of `Plugin` dataclasses. Tool
files are loaded by path (importlib, no sys.path requirement) so a plugin does
not need to be installed. Errors are handled per-plugin: a broken plugin is
logged and skipped, it never takes down the rest.

Persistence of the `enabled` flag: it lives in the plugin's own `plugin.json`
(the `"enabled"` field). `set_plugin_enabled(...)` rewrites that field in place,
so the state survives restarts with no side files.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Type

from vera.agent.tool import Tool

logger = logging.getLogger(__name__)

MANIFEST = "plugin.json"
SKILL_FILE = "SKILL.md"
TOOLS_DIR = "tools"


@dataclass
class Plugin:
    id: str                              # folder slug
    name: str
    version: str
    author: str
    description: str
    enabled: bool
    dir: str
    tool_classes: List[Type[Tool]] = field(default_factory=list)
    skill_text: Optional[str] = None
    # Optional pip requirements this plugin needs (installed on enable, not for
    # the lean core). `deps_import` is one import name used to probe presence.
    deps: List[str] = field(default_factory=list)
    deps_import: Optional[str] = None


def discover_plugins(plugins_dir: str) -> List[Plugin]:
    """Discover every plugin under `plugins_dir`. Missing dir → []."""
    if not plugins_dir or not os.path.isdir(plugins_dir):
        return []
    plugins: List[Plugin] = []
    for entry in sorted(os.listdir(plugins_dir)):
        pdir = os.path.join(plugins_dir, entry)
        if not os.path.isdir(pdir):
            continue
        try:
            plugin = _load_plugin(entry, pdir)
        except Exception as e:  # one broken plugin must not break the rest
            logger.warning("[plugins] skipping %r (load failed): %s", entry, e)
            continue
        if plugin is not None:
            plugins.append(plugin)
    return plugins


def _load_plugin(pid: str, pdir: str) -> Optional[Plugin]:
    manifest_path = os.path.join(pdir, MANIFEST)
    if not os.path.isfile(manifest_path):
        logger.warning("[plugins] %r has no %s, skipping", pid, MANIFEST)
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        man = json.load(f)  # invalid json raises → caught by caller, plugin skipped
    if not isinstance(man, dict):
        raise ValueError("manifest is not a JSON object")

    skill_text = None
    skill_path = os.path.join(pdir, SKILL_FILE)
    if os.path.isfile(skill_path):
        with open(skill_path, "r", encoding="utf-8") as f:
            skill_text = f.read()

    tool_classes = _load_tool_classes(pid, os.path.join(pdir, TOOLS_DIR))

    deps = man.get("deps") or []
    if not isinstance(deps, list):
        deps = []
    return Plugin(
        id=pid,
        name=man.get("name") or pid,
        version=str(man.get("version") or "0.0.0"),
        author=man.get("author") or "",
        description=man.get("description") or "",
        enabled=bool(man.get("enabled", True)),
        dir=pdir,
        tool_classes=tool_classes,
        skill_text=skill_text,
        deps=[str(d) for d in deps],
        deps_import=man.get("deps_import") or None,
    )


def _load_tool_classes(pid: str, tools_dir: str) -> List[Type[Tool]]:
    """Load every Tool subclass from `tools_dir`/*.py. A broken tool file is
    logged and skipped (the rest of the plugin still loads)."""
    if not os.path.isdir(tools_dir):
        return []
    classes: List[Type[Tool]] = []
    # Put the plugin dir on sys.path temporarily so relative imports inside the
    # plugin's tools can resolve. Restored in finally.
    plugin_root = os.path.dirname(tools_dir)
    added = plugin_root not in sys.path
    if added:
        sys.path.insert(0, plugin_root)
    try:
        for fname in sorted(os.listdir(tools_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            fpath = os.path.join(tools_dir, fname)
            try:
                module = _import_by_path(pid, fname, fpath)
            except Exception as e:  # syntax error / bad import: skip this file
                logger.warning("[plugins] %r tool %s failed to import: %s", pid, fname, e)
                continue
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, Tool)
                    and obj is not Tool
                    and obj.__module__ == module.__name__
                ):
                    classes.append(obj)
    finally:
        if added:
            try:
                sys.path.remove(plugin_root)
            except ValueError:
                pass
    return classes


def _import_by_path(pid: str, fname: str, fpath: str):
    """Import a module from an explicit file path with a unique module name so
    two plugins can ship a tools/mytool.py without clobbering each other."""
    mod_name = f"vera_plugin_{pid}_{os.path.splitext(fname)[0]}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(mod_name, fpath)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build spec for {fpath}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


def set_plugin_enabled(plugins_dir: str, plugin_id: str, enabled: bool) -> bool:
    """Persist the enabled flag into the plugin's plugin.json. Returns True on
    success, False if the plugin (or its manifest) does not exist."""
    manifest_path = os.path.join(plugins_dir, plugin_id, MANIFEST)
    if not os.path.isfile(manifest_path):
        return False
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            man = json.load(f)
        if not isinstance(man, dict):
            return False
        man["enabled"] = bool(enabled)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(man, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except Exception as e:
        logger.warning("[plugins] could not set enabled for %r: %s", plugin_id, e)
        return False


def _probe_name(plugin: "Plugin") -> Optional[str]:
    """Import name used to check whether the plugin's deps are already present."""
    if plugin.deps_import:
        return plugin.deps_import
    if plugin.deps:
        # naive fallback: package name before any version/extra marker
        first = plugin.deps[0]
        for sep in ("==", ">=", "<=", "~=", ">", "<", "[", " "):
            first = first.split(sep)[0]
        return first.strip() or None
    return None


def plugin_missing_deps(plugin: "Plugin") -> List[str]:
    """The plugin's declared pip requirements when they are not importable yet.
    Empty list when nothing is declared or the deps already resolve."""
    if not plugin.deps:
        return []
    probe = _probe_name(plugin)
    if probe and importlib.util.find_spec(probe) is not None:
        return []
    return list(plugin.deps)


def install_packages(requirements: List[str], target_dir: str, *,
                     python: Optional[str] = None,
                     runner: Optional[Callable] = None) -> bool:
    """pip-install `requirements` into `target_dir` (which must be on sys.path).

    `python` defaults to the current interpreter (inside Unreal that IS the
    embedded one, so wheels match). `runner` is injectable for tests; it defaults
    to subprocess.check_call. Returns True on success; never raises."""
    if not requirements:
        return True
    python = python or sys.executable
    cmd = [python, "-m", "pip", "install", "--target", target_dir, *requirements]
    runner = runner or subprocess.check_call
    try:
        os.makedirs(target_dir, exist_ok=True)
        runner(cmd)
    except Exception as e:
        logger.error("[plugins] dep install failed for %s: %s", requirements, e)
        return False
    importlib.invalidate_caches()  # make freshly-installed packages importable now
    return True
