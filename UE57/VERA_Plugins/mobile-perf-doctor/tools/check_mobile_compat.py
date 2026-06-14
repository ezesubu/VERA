"""check_mobile_compat — heuristic scan of project materials for mobile risks.

Runs a curated, main-thread-safe script inside the live Unreal editor via the
bridge. It walks the AssetRegistry for Material assets and flags the ones that
look risky for a mobile package. The flagging is HEURISTIC (see SKILL.md): the
strongest signal is the name pattern of the known-bad gFur / PCW-GFur_Advanced
shader, which fails to compile on UE5.7 and produces a null material that
SIGSEGV-crashes on device.
"""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

# Curated introspection script. Everything risky is wrapped in try/except so a
# single un-loadable asset never aborts the whole scan; partial results print.
_SCRIPT = r"""
import unreal, json

# Known-bad name fragments (case-insensitive). gFur / PCW-GFur_Advanced is the
# headline offender: fails to compile on UE5.7 -> null material -> SIGSEGV on mobile.
BAD_PATTERNS = ["gfur", "pcw-gfur", "gfur_advanced"]
# Instruction-count threshold above which a material is "expensive" for mobile.
INSTR_THRESHOLD = 200

result = {
    "scanned": 0,
    "loaded": 0,
    "ok": 0,
    "flagged": [],
    "notes": [],
}

try:
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
except Exception as e:
    print(json.dumps({"error": "AssetRegistry unavailable: %s" % e}))
    raise SystemExit

# Gather Material + MaterialInstance assets without forcing a full load up front.
assets = []
for cls in ("Material", "MaterialInstanceConstant"):
    try:
        found = ar.get_assets_by_class(unreal.TopLevelAssetPath("/Script/Engine", cls), False)
        assets.extend(list(found))
    except Exception as e:
        # Older signature fallback (4.x/early 5.x): get_assets_by_class(name, recursive)
        try:
            found = ar.get_assets_by_class(cls, False)
            assets.extend(list(found))
        except Exception as e2:
            result["notes"].append("could not enumerate %s: %s" % (cls, e2))

result["scanned"] = len(assets)

def _instruction_count(mat):
    # Best-effort base-pass instruction count; returns int or None.
    try:
        stats = unreal.MaterialEditingLibrary.get_statistics(mat)
        # get_statistics returns a struct in some builds; degrade if absent.
        if stats is not None:
            for prop in ("num_pixel_shader_instructions", "num_instructions"):
                try:
                    v = getattr(stats, prop, None)
                    if v is not None:
                        return int(v)
                except Exception:
                    pass
    except Exception:
        pass
    return None

def _sampler_count(mat):
    # Best-effort texture sampler count; returns int or None.
    try:
        textures = unreal.MaterialEditingLibrary.get_used_textures(mat)
        if textures is not None:
            return len(list(textures))
    except Exception:
        pass
    return None

for a in assets:
    try:
        name = str(a.asset_name)
    except Exception:
        name = "<unknown>"
    try:
        path = str(a.package_name)
    except Exception:
        path = "<unknown>"

    reasons = []
    low = name.lower()
    if any(p in low for p in BAD_PATTERNS):
        reasons.append("name matches known-bad gFur/PCW-GFur shader (fails to compile on UE5.7 -> null material -> SIGSEGV on mobile)")

    mat = None
    try:
        mat = unreal.AssetRegistryHelpers.get_asset(a)
        if mat is not None:
            result["loaded"] += 1
    except Exception:
        mat = None

    if mat is not None:
        instr = _instruction_count(mat)
        if instr is not None and instr > INSTR_THRESHOLD:
            reasons.append("high instruction count (%d > %d)" % (instr, INSTR_THRESHOLD))
        samplers = _sampler_count(mat)
        if samplers is not None and samplers > 8:
            reasons.append("many texture samplers (%d; mobile budget is ~8/16)" % samplers)

    if reasons:
        result["flagged"].append({"name": name, "path": path, "reasons": reasons})
    else:
        result["ok"] += 1

# Build a concise human-readable report.
lines = []
lines.append("Mobile compatibility scan (heuristic):")
lines.append("  materials scanned: %d (loaded for deep checks: %d)" % (result["scanned"], result["loaded"]))
lines.append("  OK: %d   FLAGGED: %d" % (result["ok"], len(result["flagged"])))
if result["flagged"]:
    lines.append("")
    lines.append("FLAGGED:")
    for f in result["flagged"]:
        lines.append("  - %s  [%s]" % (f["name"], f["path"]))
        for r in f["reasons"]:
            lines.append("      * %s" % r)
else:
    lines.append("  No mobile-incompatibility risks matched the heuristics.")
if result["notes"]:
    lines.append("")
    lines.append("Notes / degraded checks:")
    for n in result["notes"]:
        lines.append("  - %s" % n)
lines.append("")
lines.append("(Heuristic scan: name patterns + reachable instruction/sampler stats. "
             "Absence of flags is not a guarantee of mobile safety.)")
print("\n".join(lines))
"""


class CheckMobileCompatTool(Tool):
    name = "check_mobile_compat"
    description = (
        "Scan the project's materials (via the AssetRegistry) for mobile-incompatibility "
        "risks and return a concise OK-vs-flagged report. Flags materials matching the "
        "known-bad gFur / PCW-GFur_Advanced shader (fails to compile on UE5.7 -> null "
        "material -> SIGSEGV crash on mobile) and, when reachable, materials with very high "
        "instruction or texture-sampler counts. Heuristic. USE THIS BEFORE packaging the "
        "project for mobile, or whenever the user worries about mobile crashes or material cost."
    )
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        ctx.report("MobilePerfDoctor", "scanning materials for mobile-compat risks")
        try:
            resp = send_json(ctx.bridge_port, {"script": _SCRIPT})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not reach the Unreal editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "(no materials found)")
        return ToolResult(resp.get("error") or "editor script failed", is_error=True)
