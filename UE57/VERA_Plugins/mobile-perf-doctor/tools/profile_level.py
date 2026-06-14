"""profile_level — quick read-only cost stats of the open level.

Reuses the EditorActorSubsystem pattern from inspect_level.py: counts actors,
lights (split static vs dynamic where determinable), static-mesh actors, and
sums triangle counts when cheaply obtainable from the static-mesh assets. Calls
into per-actor APIs are individually guarded so one odd actor never aborts the
profile; it surfaces obvious red flags (e.g. lots of dynamic lights).
"""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

_SCRIPT = r"""
import unreal, json

s = {
    "total_actors": 0,
    "lights": 0,
    "dynamic_lights": 0,
    "static_mesh_actors": 0,
    "approx_triangles": 0,
    "triangles_partial": False,
    "by_class": {},
    "red_flags": [],
    "notes": [],
}

try:
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = eas.get_all_level_actors()
except Exception as e:
    print(json.dumps({"error": "EditorActorSubsystem unavailable: %s" % e}))
    raise SystemExit

s["total_actors"] = len(actors)

def _tris_for_mesh(mesh):
    # Best-effort triangle count for a StaticMesh asset (LOD0). int or None.
    try:
        lods = mesh.get_num_lods()
    except Exception:
        lods = None
    try:
        # 5.x: get_num_triangles(lod_index)
        return int(mesh.get_num_triangles(0))
    except Exception:
        pass
    return None

for a in actors:
    try:
        cls = a.get_class().get_name()
    except Exception:
        cls = "<unknown>"
    s["by_class"][cls] = s["by_class"].get(cls, 0) + 1

    if "Light" in cls:
        s["lights"] += 1
        # Mobility "Movable"/"Stationary" => dynamic-ish cost on mobile.
        try:
            root = a.get_editor_property("root_component")
            mob = root.get_editor_property("mobility")
            if mob in (unreal.ComponentMobility.MOVABLE, unreal.ComponentMobility.STATIONARY):
                s["dynamic_lights"] += 1
        except Exception:
            pass

    if cls == "StaticMeshActor":
        s["static_mesh_actors"] += 1
        try:
            comp = a.static_mesh_component
            mesh = comp.get_editor_property("static_mesh") if comp else None
            if mesh is not None:
                t = _tris_for_mesh(mesh)
                if t is not None:
                    s["approx_triangles"] += t
                else:
                    s["triangles_partial"] = True
        except Exception:
            s["triangles_partial"] = True

# Red-flag heuristics for mobile.
if s["dynamic_lights"] > 4:
    s["red_flags"].append("%d dynamic/stationary lights — costly on mobile (prefer baked/static)" % s["dynamic_lights"])
if s["total_actors"] > 5000:
    s["red_flags"].append("very high actor count (%d) — consider HLODs / instancing" % s["total_actors"])
if s["approx_triangles"] > 5_000_000:
    s["red_flags"].append("~%d triangles in static meshes — heavy for mobile" % s["approx_triangles"])

# Concise report.
lines = []
lines.append("Level profile (read-only):")
lines.append("  actors: %d   lights: %d (dynamic/stationary: %d)   static-mesh actors: %d"
             % (s["total_actors"], s["lights"], s["dynamic_lights"], s["static_mesh_actors"]))
tri = s["approx_triangles"]
tri_str = ("~%d%s" % (tri, " (partial — some meshes unreadable)" if s["triangles_partial"] else "")) if tri else \
          ("unavailable" if s["triangles_partial"] else "0")
lines.append("  approx triangles (static meshes, LOD0): %s" % tri_str)
# Top classes by count.
top = sorted(s["by_class"].items(), key=lambda kv: kv[1], reverse=True)[:8]
if top:
    lines.append("  top classes: " + ", ".join("%s=%d" % (k, v) for k, v in top))
if s["red_flags"]:
    lines.append("")
    lines.append("RED FLAGS:")
    for f in s["red_flags"]:
        lines.append("  - %s" % f)
else:
    lines.append("  No obvious red flags from these heuristics.")
print("\n".join(lines))
"""


class ProfileLevelTool(Tool):
    name = "profile_level"
    description = (
        "Quick read-only cost profile of the level currently open in the editor: actor "
        "count, light count (with dynamic/stationary lights called out), static-mesh actor "
        "count, an approximate triangle total when cheaply obtainable, and obvious mobile "
        "red flags (e.g. many dynamic lights, very high actor/triangle counts). USE THIS to "
        "sanity-check scene cost before packaging or when the editor/runtime feels heavy."
    )
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        ctx.report("MobilePerfDoctor", "profiling the open level")
        try:
            resp = send_json(ctx.bridge_port, {"script": _SCRIPT})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not reach the Unreal editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "(level appears empty)")
        return ToolResult(resp.get("error") or "editor script failed", is_error=True)
