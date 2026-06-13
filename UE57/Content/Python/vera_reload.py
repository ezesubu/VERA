"""Hot-reload the VERA UI inside the editor (works around UE's module cache).

Run from the editor's Python console (single line):
    exec(open(r"E:/PCW/VERA/UE57/Content/Python/vera_reload.py").read())

Adds the UE57 Content/Python folder to sys.path first, so it works even when
the editor has a different project open.
"""
import importlib
import os
import sys

import unreal

VERA_PY_DIR = r"E:/PCW/VERA/UE57/Content/Python"

try:
    # 0) make sure VERA's Python folder is importable
    if VERA_PY_DIR not in sys.path:
        sys.path.insert(0, VERA_PY_DIR)
        unreal.log(f"[vera_reload] added to sys.path: {VERA_PY_DIR}")

    import vera_ui

    # 1) close the old window if it exists
    try:
        if getattr(vera_ui, "global_vera_window", None):
            vera_ui.global_vera_window.close()
    except Exception as e:
        unreal.log_warning(f"[vera_reload] could not close old window: {e}")

    # 2) clear the tick guard so the tick re-registers against the new module
    if hasattr(unreal, "_vera_qt_tick_registered_v6"):
        del unreal._vera_qt_tick_registered_v6

    # 3) reload the module and open fresh
    importlib.reload(vera_ui)
    vera_ui.global_vera_window = None
    vera_ui.open_vera_ui()
    unreal.log("[vera_reload] VERA UI reloaded and opened (fresh module).")
except Exception as e:
    unreal.log_error(f"[vera_reload] FAILED: {e}")
    import traceback
    unreal.log_error(traceback.format_exc())
