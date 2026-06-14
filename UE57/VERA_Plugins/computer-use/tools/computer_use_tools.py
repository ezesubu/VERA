"""Computer-use tools (opt-in plugin) — screen capture + click.

Last resort for editor UI with no Python API. VERA reads the screenshot directly
(it is multimodal), so there is no OCR: just capture → look → click coordinates.

`pyautogui` (and Pillow) are installed only when this plugin is enabled; both are
imported lazily so the plugin still loads before its deps are present — the tools
return a clear, actionable error in that window instead of failing to import.

Caveat: screen control needs the editor window in the foreground. Prefer the
`unreal` API and dedicated tools whenever they can reach the target.
"""
from __future__ import annotations

import base64
import io

from vera.agent.tool import Tool, ToolContext, ToolResult, image_block

_MISSING = ("This needs the 'pyautogui' package. Enable the Computer Use plugin "
            "(it installs its deps), or install manually: pip install pyautogui Pillow.")


def _pyautogui():
    """Import pyautogui lazily; returns (module, error_message_or_None)."""
    try:
        import pyautogui  # noqa: PLC0415 (lazy on purpose)
        return pyautogui, None
    except Exception as e:  # not installed yet, or no display available
        return None, f"{_MISSING} ({e})"


class ScreenCaptureTool(Tool):
    name = "screen_capture"
    description = (
        "Takes a screenshot of the whole screen and returns it as an image so you "
        "can SEE editor UI that has no Python API (menus, Project Settings, modal "
        "dialogs). Use it to locate a control before clicking it with screen_click. "
        "The editor must be in the foreground. Prefer dedicated tools / the unreal "
        "API when they can read what you need — this is a last resort."
    )
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        pyautogui, err = _pyautogui()
        if err:
            return ToolResult(err, is_error=True)
        ctx.report("ComputerUse", "capturing the screen")
        try:
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            data = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            return ToolResult(f"Could not capture the screen: {e}", is_error=True)
        return ToolResult([
            {"type": "text", "text": f"Screen captured ({img.width}x{img.height})."},
            image_block(data, "image/png"),
        ])


class ScreenClickTool(Tool):
    name = "screen_click"
    description = (
        "Moves the mouse to (x, y) in SCREEN pixels and clicks. Use only for UI "
        "with no Python API, after locating the target with screen_capture. The "
        "editor must be in the foreground. Coordinates are absolute screen pixels."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "absolute screen X in pixels"},
            "y": {"type": "integer", "description": "absolute screen Y in pixels"},
            "button": {"type": "string", "enum": ["left", "right", "middle"],
                       "description": "mouse button (default left)"},
            "clicks": {"type": "integer", "description": "number of clicks (default 1)"},
        },
        "required": ["x", "y"],
    }
    destructive = True  # clicking changes editor state → confirmation gate

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        pyautogui, err = _pyautogui()
        if err:
            return ToolResult(err, is_error=True)
        try:
            x = int(args["x"])
            y = int(args["y"])
        except (KeyError, TypeError, ValueError):
            return ToolResult("screen_click needs integer 'x' and 'y'.", is_error=True)
        button = args.get("button") or "left"
        clicks = int(args.get("clicks") or 1)
        ctx.report("ComputerUse", f"clicking at ({x}, {y})")
        try:
            pyautogui.click(x=x, y=y, clicks=clicks, button=button)
        except Exception as e:
            return ToolResult(f"Could not click at ({x}, {y}): {e}", is_error=True)
        return ToolResult(f"Clicked {button} x{clicks} at ({x}, {y}).")
