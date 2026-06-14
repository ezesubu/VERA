"""First-run dependency bootstrap for VERA's embedded Python.

VERA's LLM brain needs a few pip packages (anthropic, openai, mcp) that are not
part of Unreal's bundled Python. They are installed once into <repo>/.ue_deps
(already on sys.path via init_unreal.py) using the editor's embedded interpreter.

Idempotent: only missing packages are installed, so on every later launch this is
a near-instant set of `find_spec` checks. Mirrors how the chat UI auto-installs
PySide6 — so "install the plugin → open VERA → it works", with no console magic.
"""
import importlib
import importlib.util
import os
import subprocess
import sys

import unreal

# (import name, pip requirement) — the brain essentials the in-editor server needs.
_REQUIRED = [
    ("anthropic", "anthropic>=0.40.0"),
    ("openai", "openai>=1.40.0"),
    ("mcp", "mcp>=1.2.0"),
]


def _embedded_python():
    """Path to the editor's embedded interpreter (cross-platform: win/mac/linux)."""
    if sys.platform == "win32":
        exe = os.path.join(sys.exec_prefix, "python.exe")
        engine_sub = os.path.join("Binaries", "ThirdParty", "Python3", "Win64", "python.exe")
    elif sys.platform == "darwin":
        exe = os.path.join(sys.exec_prefix, "bin", "python3")
        engine_sub = os.path.join("Binaries", "ThirdParty", "Python3", "Mac", "bin", "python3")
    else:
        exe = os.path.join(sys.exec_prefix, "bin", "python3")
        engine_sub = os.path.join("Binaries", "ThirdParty", "Python3", "Linux", "bin", "python3")
    if os.path.exists(exe):
        return exe
    return os.path.join(unreal.Paths.engine_dir(), engine_sub)


def _missing():
    """pip requirements whose import is not resolvable in the current interpreter."""
    return [req for mod, req in _REQUIRED if importlib.util.find_spec(mod) is None]


def ensure_deps(deps_dir):
    """Install any missing brain deps into `deps_dir`. Returns True when all are
    present (after any install). Never raises: a failure is logged and VERA
    degrades gracefully (the UI still opens; the brain reports the missing dep)."""
    missing = _missing()
    if not missing:
        return True

    unreal.log(f"[VERA] First-run setup: installing {len(missing)} Python package(s) "
               f"into {deps_dir} (one time, please wait)...")
    try:
        os.makedirs(deps_dir, exist_ok=True)
        subprocess.check_call(
            [_embedded_python(), "-m", "pip", "install", "--target", deps_dir, *missing])
    except Exception as e:
        unreal.log_error(
            f"[VERA] dependency install failed: {e}. Install manually with:\n"
            f"  pip install --target \"{deps_dir}\" " + " ".join(missing))
        return False

    # The freshly-installed packages live on a path already in sys.path; just
    # refresh the finder caches so they import without restarting the editor.
    importlib.invalidate_caches()
    still = _missing()
    if still:
        unreal.log_error(f"[VERA] still missing after install: {still}")
        return False
    unreal.log("[VERA] dependencies ready.")
    return True
