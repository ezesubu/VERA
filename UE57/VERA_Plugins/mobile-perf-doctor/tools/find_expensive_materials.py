"""find_expensive_materials — rank project materials by an expense heuristic.

Walks the AssetRegistry for materials, scores each by reachable cost signals
(pixel-shader instruction count and texture-sampler count), and returns the
top N. Every per-material probe is guarded so one bad asset never aborts the
ranking; materials whose stats are unreachable still appear with a note.
"""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

# {LIMIT} is substituted with the requested top-N before sending.
_SCRIPT_TMPL = r"""
import unreal, json

LIMIT = {LIMIT}

out = {"scanned": 0, "ranked": [], "notes": []}

try:
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
except Exception as e:
    print(json.dumps({"error": "AssetRegistry unavailable: %s" % e}))
    raise SystemExit

assets = []
for cls in ("Material", "MaterialInstanceConstant"):
    try:
        found = ar.get_assets_by_class(unreal.TopLevelAssetPath("/Script/Engine", cls), False)
        assets.extend(list(found))
    except Exception:
        try:
            found = ar.get_assets_by_class(cls, False)
            assets.extend(list(found))
        except Exception as e2:
            out["notes"].append("could not enumerate %s: %s" % (cls, e2))

out["scanned"] = len(assets)

def _instr(mat):
    try:
        stats = unreal.MaterialEditingLibrary.get_statistics(mat)
        if stats is not None:
            for prop in ("num_pixel_shader_instructions", "num_instructions"):
                v = getattr(stats, prop, None)
                if v is not None:
                    return int(v)
    except Exception:
        pass
    return None

def _samplers(mat):
    # Best-effort texture sampler count; returns int or None.
    try:
        textures = unreal.MaterialEditingLibrary.get_used_textures(mat)
        if textures is not None:
            return len(list(textures))
    except Exception:
        pass
    return None

scored = []
for a in assets:
    try:
        name = str(a.asset_name)
    except Exception:
        name = "<unknown>"
    try:
        path = str(a.package_name)
    except Exception:
        path = "<unknown>"

    mat = None
    try:
        mat = unreal.AssetRegistryHelpers.get_asset(a)
    except Exception:
        mat = None

    instr = _instr(mat) if mat is not None else None
    samp = _samplers(mat) if mat is not None else None

    # Expense heuristic: instruction count dominates; each sampler ~ a few instr.
    if instr is None and samp is None:
        score = -1  # unknown cost: sorts to the bottom but still listed
        note = "stats unreachable"
    else:
        score = (instr or 0) + (samp or 0) * 8
        note = ""
    scored.append({"name": name, "path": path, "instr": instr, "samplers": samp,
                    "score": score, "note": note})

# Highest score first; unknowns (-1) naturally fall to the end.
scored.sort(key=lambda m: m["score"], reverse=True)
top = scored[:LIMIT]

lines = []
lines.append("Most expensive materials (heuristic, top %d of %d scanned):" % (len(top), out["scanned"]))
if not top:
    lines.append("  (no materials found)")
for i, m in enumerate(top, 1):
    instr = m["instr"] if m["instr"] is not None else "?"
    samp = m["samplers"] if m["samplers"] is not None else "?"
    extra = ("  <%s>" % m["note"]) if m["note"] else ""
    lines.append("  %2d. %s  (instr=%s, samplers=%s, score=%s)%s"
                 % (i, m["name"], instr, samp, m["score"], extra))
    lines.append("       %s" % m["path"])
if out["notes"]:
    lines.append("")
    lines.append("Notes / degraded checks:")
    for n in out["notes"]:
        lines.append("  - %s" % n)
lines.append("")
lines.append("(Heuristic ranking: pixel-shader instructions + samplers*8. "
             "'?' means the stat was not reachable via the Python API in this build.)")
print("\n".join(lines))
"""


class FindExpensiveMaterialsTool(Tool):
    name = "find_expensive_materials"
    description = (
        "List the project's materials ranked by an expense heuristic (pixel-shader "
        "instruction count plus texture-sampler count, when reachable) and return the "
        "top N (arg `limit`, default 10). USE THIS to spot the heaviest shaders before "
        "packaging for mobile or when chasing a GPU bottleneck. Heuristic: materials "
        "whose cost cannot be read via Python are still listed, marked 'stats unreachable'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many of the most expensive materials to return (default 10).",
                "minimum": 1,
                "maximum": 100,
            }
        },
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        try:
            limit = int(args.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 100))
        ctx.report("MobilePerfDoctor", f"ranking materials by cost (top {limit})")
        script = _SCRIPT_TMPL.replace("{LIMIT}", str(limit))
        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not reach the Unreal editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "(no materials found)")
        return ToolResult(resp.get("error") or "editor script failed", is_error=True)
