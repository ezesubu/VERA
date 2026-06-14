"""Blueprint Forge (plugin) — create Actor Blueprints via Unreal's Graph API.

Ports the old BlueprintGenerator to an AgentLoop Tool. It runs a curated script
through the bridge: BlueprintFactory + AssetTools create the asset,
BlueprintEditorLibrary (UE 5.2+) adds components and compiles, then the asset is
saved. No clicking, no perception — pure `unreal` API.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

# Curated, main-thread-safe generation script. Inputs are injected as JSON
# literals (json.dumps yields valid Python literals for str/list).
_SCRIPT_TMPL = '''
import unreal, json

_COMP = {
    "scene": "SceneComponent",
    "static_mesh": "StaticMeshComponent",
    "box_collision": "BoxComponent",
    "sphere_collision": "SphereComponent",
    "capsule_collision": "CapsuleComponent",
    "point_light": "PointLightComponent",
}

def _make(name, path, parent_name, components):
    out = {"ok": False, "path": "", "components": [], "warnings": []}
    parent = getattr(unreal, parent_name, None) or unreal.Actor
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    bp = tools.create_asset(name, path, unreal.Blueprint, factory)
    if not bp:
        out["error"] = "could not create the Blueprint (name/path already in use?)"
        return out
    out["path"] = bp.get_path_name()
    BEL = getattr(unreal, "BlueprintEditorLibrary", None)
    if components and BEL and hasattr(BEL, "add_component_to_blueprint"):
        root = None
        try:
            root = BEL.add_component_to_blueprint(bp, unreal.SceneComponent)
            out["components"].append("scene(root)")
        except Exception as e:
            out["warnings"].append("root scene: " + str(e))
        for c in components:
            cls_name = _COMP.get(c)
            if not cls_name:
                out["warnings"].append("unknown component: " + str(c)); continue
            cls = getattr(unreal, cls_name, None)
            if cls is None:
                out["warnings"].append("class not found: " + cls_name); continue
            try:
                BEL.add_component_to_blueprint(bp, cls, root)
                out["components"].append(c)
            except Exception as e:
                out["warnings"].append(str(c) + ": " + str(e))
    elif components and not BEL:
        out["warnings"].append("BlueprintEditorLibrary unavailable (needs UE 5.2+); created without components")
    try:
        if BEL and hasattr(BEL, "compile_blueprint"):
            BEL.compile_blueprint(bp)
    except Exception as e:
        out["warnings"].append("compile: " + str(e))
    try:
        unreal.EditorAssetLibrary.save_asset(out["path"].split(".")[0])
    except Exception as e:
        out["warnings"].append("save: " + str(e))
    out["ok"] = True
    return out

print(json.dumps(_make(%(name)s, %(path)s, %(parent)s, %(components)s)))
'''


class CreateBlueprintTool(Tool):
    name = "create_blueprint"
    description = (
        "Creates a new Actor Blueprint via Unreal's Python Graph API and saves it "
        "(no clicking). Optionally adds components (scene, static_mesh, "
        "box_collision, sphere_collision, capsule_collision, point_light) and "
        "compiles. Use when the user asks to create a Blueprint class."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "bp_name": {"type": "string", "description": "Blueprint asset name, e.g. BP_SpikeTrap"},
            "package_path": {"type": "string",
                             "description": "content path (default /Game/VERA_Autogen)"},
            "parent_class": {"type": "string",
                             "description": "parent unreal class name (default Actor)"},
            "components": {
                "type": "array",
                "items": {"type": "string",
                          "enum": ["scene", "static_mesh", "box_collision",
                                   "sphere_collision", "capsule_collision", "point_light"]},
                "description": "components to add under a scene root",
            },
        },
        "required": ["bp_name"],
    }
    destructive = True  # writes a new asset into the project → confirmation gate

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        bp_name = (args.get("bp_name") or "").strip()
        if not bp_name:
            return ToolResult("create_blueprint needs a 'bp_name'.", is_error=True)
        package_path = (args.get("package_path") or "/Game/VERA_Autogen").rstrip("/")
        parent_class = (args.get("parent_class") or "Actor").strip()
        components = args.get("components") or []
        if not isinstance(components, list):
            components = []

        script = _SCRIPT_TMPL % {
            "name": json.dumps(bp_name),
            "path": json.dumps(package_path),
            "parent": json.dumps(parent_class),
            "components": json.dumps(components),
        }
        ctx.report("BlueprintForge", f"creating Blueprint {bp_name}")
        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not reach the editor: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "Blueprint creation failed", is_error=True)

        try:
            data = json.loads((resp.get("output") or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return ToolResult(resp.get("output") or "(no output)", is_error=True)
        if not data.get("ok"):
            return ToolResult(data.get("error") or "Blueprint creation failed", is_error=True)

        parts = [f"Created Blueprint {data['path']}"]
        if data.get("components"):
            parts.append("components: " + ", ".join(data["components"]))
        if data.get("warnings"):
            parts.append("warnings: " + "; ".join(data["warnings"]))
        return ToolResult(". ".join(parts) + ".")
