"""
VERA UE Python Bridge — Direct Unreal Engine scripting via Python.

This is VERA's most powerful and token-free execution layer.
Instead of visually navigating menus, we directly call the UE5 Python API
through a persistent HTTP bridge running inside the Unreal Editor.

Setup: Enable "Python Editor Script Plugin" in UE5 editor,
then run vera/tools/ue_bridge_server.py inside UE's Python console.
"""

from __future__ import annotations

import json
import logging
import socket
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default port for the UE Python bridge server
UE_BRIDGE_PORT = 9877


# ── Pre-built UE Python scripts for common tasks ──────────────────────────────

SCRIPTS = {
    "get_default_map": """
import unreal
s = unreal.get_default_object(unreal.GameMapsSettings)
print(s.get_editor_property('game_default_map'))
""",
    "set_default_map": """
import unreal
s = unreal.get_default_object(unreal.GameMapsSettings)
s.set_editor_property('game_default_map', '{map_path}')
s.set_editor_property('editor_startup_map', '{map_path}')
print('Map set to {map_path}')
""",
    "get_project_name": """
import unreal
print(unreal.SystemLibrary.get_game_name())
""",
    "save_all": """
import unreal
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
print('Saved all dirty packages.')
""",
    "list_open_maps": """
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
print(world.get_path_name())
""",
    "open_project_settings": """
import unreal
unreal.SystemLibrary.execute_console_command(None, 'Editor.OpenProjectSettings')
print('Project settings opened.')
""",
}


class UEPythonBridge:
    """
    Executes Python scripts directly inside the UE5 editor via a
    local TCP socket bridge. Zero LLM tokens — direct API calls.

    The bridge server must be running inside UE's Python console.
    See: vera/tools/ue_bridge_server.py
    """

    def __init__(self, port: int = UE_BRIDGE_PORT):
        self.port = port
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if the UE Python bridge server is running."""
        if self._available is not None:
            return self._available
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1.0):
                self._available = True
        except (ConnectionRefusedError, socket.timeout):
            self._available = False
        return self._available

    def execute(self, script: str) -> dict:
        """
        Execute a Python script inside the UE editor.

        Args:
            script: Valid UE Python script string

        Returns:
            {"success": bool, "output": str, "error": str}
        """
        if not self.is_available():
            logger.warning("UE Python bridge not available. Skipping direct API call.")
            return {"success": False, "error": "Bridge not available"}

        try:
            payload = json.dumps({"script": script}) + "\n"
            with socket.create_connection(("127.0.0.1", self.port), timeout=10.0) as sock:
                sock.sendall(payload.encode("utf-8"))
                response = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk

            result = json.loads(response.decode("utf-8"))
            logger.info(f"UE Bridge result: {result.get('output', '')}")
            return result

        except Exception as e:
            logger.error(f"UE Bridge execution failed: {e}")
            return {"success": False, "error": str(e)}

    def set_default_map(self, map_path: str) -> dict:
        """Convenience: Set the game default map directly."""
        script = SCRIPTS["set_default_map"].format(map_path=map_path)
        return self.execute(script)

    def save_all(self) -> dict:
        """Convenience: Save all dirty packages."""
        return self.execute(SCRIPTS["save_all"])

    def get_current_map(self) -> Optional[str]:
        """Convenience: Get the currently open map path."""
        result = self.execute(SCRIPTS["list_open_maps"])
        if result["success"]:
            return result.get("output", "").strip()
        return None
