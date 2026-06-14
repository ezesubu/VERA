"""Layer 1 (dedicated): read-only inspection of the level open in the editor.

Perception tool: the brain uses it to understand what is in the scene before
acting (how many actors, of what classes, lights, static meshes). Runs a curated
script via the bridge — the model does not have to re-write the introspection.
"""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

# Curated introspection script (main-thread safe; uses the 5.x subsystem).
_SCRIPT = """
import unreal, json
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = eas.get_all_level_actors()
summary = {"total_actors": len(actors), "lights": 0, "static_meshes": 0, "by_class": {}}
for a in actors:
    cls = a.get_class().get_name()
    summary["by_class"][cls] = summary["by_class"].get(cls, 0) + 1
    if "Light" in cls:
        summary["lights"] += 1
    if cls == "StaticMeshActor":
        summary["static_meshes"] += 1
print(json.dumps(summary, indent=2, sort_keys=True))
"""


class InspectLevelTool(Tool):
    name = "inspect_level"
    description = (
        "Inspects (read-only) the level open in the Unreal editor: returns "
        "the total number of actors, how many lights and static meshes there are, "
        "and a per-class count. Use this tool to understand the scene before modifying it."
    )
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        ctx.report("InspectLevel", "reading the open level")
        try:
            resp = send_json(ctx.bridge_port, {"script": _SCRIPT})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not inspect the level: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "(empty level)")
        return ToolResult(resp.get("error") or "failed to inspect the level", is_error=True)
