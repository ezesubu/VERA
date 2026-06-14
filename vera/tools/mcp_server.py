"""VERA MCP server: exposes the Unreal editor as tools for Claude Code.

The functions in this module are pure/testable; the FastMCP wiring lives in main().
"""
import os
import time
import uuid
from pathlib import Path

from vera.tools.ue_conn import UEConnectionError, UETimeoutError, send_json

# Repo root = two levels above vera/tools/
_REPO_ROOT = Path(__file__).resolve().parents[2]
UE_PROJECT_DIR = Path(os.environ.get("VERA_UE_PROJECT_DIR", _REPO_ROOT / "UE57"))
LOG_PATH = UE_PROJECT_DIR / "Saved" / "Logs" / "UE57.log"
SCREENSHOTS_DIR = UE_PROJECT_DIR / "Saved" / "Screenshots" / "WindowsEditor"

BRIDGE_PORT = int(os.environ.get("VERA_BRIDGE_PORT", "9878"))
BACKEND_PORT = int(os.environ.get("VERA_BACKEND_PORT", "9880"))

BRIDGE_DOWN_MSG = (
    "Unreal is not running or the bridge did not load. Open the UE57 project "
    "(the bridge auto-starts with init_unreal.py) or run `import vera_bridge` "
    "in the editor's Python console. Try `ue_status` to diagnose."
)
BACKEND_DOWN_MSG = (
    "The VERA backend (port 9880) is not running. "
    "Start it with: python -m vera.core.vera_server"
)


def tail_log(path, lines=100):
    """Last N lines of the editor log. Reads the file directly: works even if the
    editor is hung or crashed."""
    path = Path(path)
    if not path.exists():
        return f"No log at {path}. Did the editor ever open?"
    text = path.read_text(encoding="utf-8", errors="replace")
    if lines <= 0:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def run_script(script, timeout=60.0, port=None):
    """Runs Python on the editor's main thread. The UE traceback comes back as a
    normal result (success=False), not as an exception — the agent reads it and
    fixes it. success=None means timeout: the script may still be running."""
    try:
        result = send_json(port or BRIDGE_PORT, {"script": script}, timeout=timeout)
    except UETimeoutError:
        return {
            "success": None,
            "output": (
                f"The editor did not respond within {timeout:.0f}s — the script is "
                "still running (compiling shaders or loading assets can take a while). "
                "Check with ue_log or ue_status; nothing was aborted."
            ),
        }
    except UEConnectionError:
        return {"success": False, "output": "", "error": BRIDGE_DOWN_MSG}
    return result


def check_status(bridge_port=None, backend_port=None):
    """Pings bridge and backend. For the bridge it requests the engine version."""
    status = {"bridge": {"online": False, "engine_version": None}, "backend": {"online": False}}

    version_script = "import unreal\nprint(unreal.SystemLibrary.get_engine_version())"
    try:
        result = send_json(
            bridge_port or BRIDGE_PORT, {"script": version_script}, timeout=10.0
        )
        status["bridge"]["online"] = bool(result.get("success"))
        status["bridge"]["engine_version"] = result.get("output", "").strip()
    except (UEConnectionError, UETimeoutError) as e:
        status["bridge"]["error"] = f"{BRIDGE_DOWN_MSG} ({e})"

    try:
        result = send_json(
            backend_port or BACKEND_PORT, {"command": "hello world"}, timeout=10.0
        )
        status["backend"]["online"] = result.get("status") == "success"
    except (UEConnectionError, UETimeoutError) as e:
        status["backend"]["error"] = f"{BACKEND_DOWN_MSG} ({e})"

    return status


def send_vera_command(text, timeout=300.0, port=None):
    """High-level command to the agent pipeline (streaming protocol).
    Returns the final event + the full list in "events"."""
    from vera.tools.ue_conn import send_json_stream
    try:
        events = send_json_stream(port or BACKEND_PORT, {"command": text}, timeout=timeout)
    except UEConnectionError:
        return {"status": "error", "message": BACKEND_DOWN_MSG, "events": []}
    except UETimeoutError:
        return {
            "status": "error",
            "message": f"The backend did not respond within {timeout:.0f}s. Check its logs.",
            "events": [],
        }
    final = events[-1]
    if final.get("type") != "final":
        interrupted = "The backend closed the stream without a final event (pipeline interrupted)."
        return {"status": "error", "msg": interrupted, "message": interrupted, "events": events}
    return {
        "status": final.get("status", "error"),
        "msg": final.get("msg", ""),
        "message": final.get("msg", ""),  # compat with the existing vera_command tool
        "events": events,
    }


_SCREENSHOT_SCRIPT = (
    "import unreal\n"
    'unreal.AutomationLibrary.take_high_res_screenshot(1280, 720, "{name}")\n'
    "print('screenshot requested: {name}')"
)


def request_screenshot(timeout=20.0, port=None, screenshots_dir=None):
    """Requests a viewport capture and waits for the PNG to appear on disk.

    Returns the Path of the PNG, or None if it failed (bridge down or the file
    never appeared). take_high_res_screenshot is asynchronous: UE writes the
    file a few frames after running the script.
    """
    target_dir = Path(screenshots_dir) if screenshots_dir else SCREENSHOTS_DIR
    name = f"vera_{uuid.uuid4().hex[:8]}.png"

    result = run_script(_SCREENSHOT_SCRIPT.format(name=name), timeout=15.0, port=port)
    if result.get("success") is False:
        return None

    target = target_dir / name
    deadline = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        if target.exists():
            size = target.stat().st_size
            # UE writes directly to the final path (no temp+rename): requiring a
            # stable size across two consecutive polls avoids returning a half-written PNG.
            if size > 0 and size == last_size:
                return target
            last_size = size
        time.sleep(0.25)
    return None


def main():
    # Import inside main(): tests import this module without needing the SDK
    from mcp.server.fastmcp import FastMCP, Image

    mcp = FastMCP("vera-ue")

    @mcp.tool()
    def ue_exec(script: str, timeout: float = 60.0) -> str:
        """Runs Python on the Unreal editor's main thread (the `unreal` module is
        available). Returns captured stdout, or the traceback if the script failed.
        If it exceeds `timeout` (seconds) it returns TIMEOUT: the script KEEPS running
        in the editor (it is not aborted); check the result with ue_log or ue_status.
        Each call uses a fresh namespace: state (variables, imports) does NOT persist between calls — include everything needed in a single script."""
        result = run_script(script, timeout=timeout)
        if result.get("success") is False:
            return f"ERROR:\n{result.get('error', result.get('output', 'no detail'))}"
        if result.get("success") is None:
            return f"TIMEOUT:\n{result.get('output', '')}"
        return result.get("output", "") or "(no output)"

    @mcp.tool()
    def ue_screenshot() -> Image:
        """Captures the editor's active viewport and returns the PNG."""
        path = request_screenshot()
        if path is None:
            raise RuntimeError(
                "Could not capture the viewport (bridge down or the capture did not appear on disk in time). " + BRIDGE_DOWN_MSG
                + " If the bridge is OK, check ue_log(100)."
            )
        return Image(data=path.read_bytes(), format="png")

    @mcp.tool()
    def ue_log(lines: int = 100) -> str:
        """Last N lines (default 100) of the editor's Output Log — reads Saved/Logs/UE57.log directly from disk: works even if the editor is hung or crashed."""
        return tail_log(LOG_PATH, lines=lines)

    @mcp.tool()
    def ue_status() -> dict:
        """Status of the bridge (9878) and the VERA backend (9880), with the engine version."""
        return check_status()

    @mcp.tool()
    def vera_command(text: str) -> str:
        """High-level command to the VERA agent pipeline (ManagerAgent → recipes). It can take several minutes: the backend calls an LLM (internal timeout 300s)."""
        result = send_vera_command(text)
        return result.get("message", str(result))

    mcp.run()


if __name__ == "__main__":
    main()
