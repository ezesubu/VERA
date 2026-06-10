"""
VERA Recipes — Pre-built workflows for common UE5 tasks.

Recipes are deterministic step sequences that execute with
zero LLM calls. They are the fastest possible execution path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vera.core.agent import VERAAgent


def setup_android_lobby_build(agent: "VERAAgent", map_path: str = "/Game/Lobby/Lobby") -> dict:
    """
    Recipe: Configure project for Android build with a single map.

    Steps:
    1. Set Game Default Map via UE Python (free)
    2. Set Editor Startup Map via UE Python (free)
    3. Save all via UE Python (free)

    Total token cost: 0
    """
    steps = [
        {
            "type": "ue_python",
            "params": {
                "script": f"""
import unreal
s = unreal.get_default_object(unreal.GameMapsSettings)
s.set_editor_property('game_default_map', '{map_path}')
s.set_editor_property('editor_startup_map', '{map_path}')
s.set_editor_property('server_default_map', '{map_path}')
print('Maps configured: {map_path}')
"""
            },
        },
        {
            "type": "ue_python",
            "params": {
                "script": """
import unreal
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
print('All packages saved.')
"""
            },
        },
    ]

    result = {"command": f"Setup Android build with map {map_path}", "steps": [], "success": True}
    for step in steps:
        step_result = agent._execute_step(step)
        result["steps"].append(step)
        if not step_result.get("success"):
            result["success"] = False
            result["error"] = step_result.get("error")
            break

    return result


def fix_mobile_sampler_limit(agent: "VERAAgent", material_path: str) -> dict:
    """
    Recipe: Open a material and report its sampler count.
    Guides the user to add a Feature Level Switch node.
    (Full automation requires Blueprints Python API — Phase 2)
    """
    steps = [
        {
            "type": "ue_python",
            "params": {
                "script": f"""
import unreal
asset = unreal.load_asset('{material_path}')
if asset:
    print(f'Material loaded: {{asset.get_name()}}')
    # Open in material editor
    unreal.AssetEditorSubsystem().open_editor_for_assets([asset])
    print('Material editor opened.')
else:
    print('ERROR: Material not found at {material_path}')
"""
            },
        }
    ]

    result = {"command": f"Fix sampler limit on {material_path}", "steps": [], "success": True}
    for step in steps:
        step_result = agent._execute_step(step)
        result["steps"].append(step)
        if not step_result.get("success"):
            result["success"] = False
            break

    return result
