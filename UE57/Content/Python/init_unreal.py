"""Unreal runs this file automatically when the project opens
(the init_unreal.py convention from the Python Editor Script Plugin)."""
import os
import sys

# QtWebEngine (the VERA chat) embedded in Unreal is fragile on the GPU process:
# the editor's own renderer conflicts with Chromium's, causing crashes
# (Unhandled Exception 0x80000003 in Qt6WebEngineCore). Forcing software rendering
# avoids it. MUST be set before QtWebEngine starts. The chat UI is light, so the
# cost is negligible.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-gpu-compositing")

# pip dependencies (anthropic, openai, etc.) for the embedded Python 3.11 live in
# <repo>/.ue_deps (override with VERA_DEPS_DIR). Install with, e.g.:
#   pip install <pkg> --target <repo>/.ue_deps --python-version 3.11 --only-binary=:all:
# Derived from this file's location so it works on any machine / OS.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))  # UE57/Content/Python → repo root
_VERA_DEPS = os.environ.get("VERA_DEPS_DIR") or os.path.join(_REPO_ROOT, ".ue_deps")
if _VERA_DEPS not in sys.path:
    sys.path.insert(0, _VERA_DEPS)

import unreal

# First-run setup: auto-install the brain's pip deps (anthropic/openai/mcp) into
# .ue_deps if they're missing, so a fresh plugin install just works. Near-instant
# once they're present.
try:
    import vera_bootstrap
    vera_bootstrap.ensure_deps(_VERA_DEPS)
except Exception as e:
    unreal.log_error("[VERA] dependency bootstrap failed: " + str(e))

# QtWebEngine requires this flag BEFORE creating any QApplication.
# We set it here (at editor startup) so open_vera_ui inherits it.
try:
    from PySide6.QtCore import Qt, QCoreApplication
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
except ImportError:
    pass  # PySide6 is installed on-demand the first time the UI opens

try:
    import vera_bridge  # noqa: F401  — TCP bridge for Claude Code/VERA (port 9878)
except Exception as e:
    unreal.log_error("[VERA] Could not start the bridge: " + str(e))

try:
    import vera_ui  # noqa: F401  — injects the VERA button into the toolbar
except Exception as e:
    unreal.log_error("[VERA] Could not load the UI: " + str(e))

# Optional demo / minigame modules (PIE only). They are NOT shipped in the
# packaged plugin, so a missing one is silent; only a real load error is logged.
for _demo in ("vera_enemy", "vera_horror", "vera_lava"):
    try:
        __import__(_demo)  # noqa: F401
    except ImportError:
        pass
    except Exception as e:
        unreal.log_error(f"[VERA] Could not load {_demo}: {e}")

try:
    import vera_server_launcher  # noqa: F401  — starts vera_server in the background
except Exception as e:
    unreal.log_error("[VERA] Could not start vera_server: " + str(e))
