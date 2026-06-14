"""clear_vibe — remove the VERA-added vibe actors, restoring the level.

Finds every level actor tagged "VERA_Vibe" (the DirectionalLight + PostProcessVolume
that set_vibe spawned) and destroys them. Idempotent and non-destructive to anything
the user authored: it only touches actors carrying VERA's tag. Reports how many were
removed. Every `unreal` call is guarded so one odd actor never aborts the cleanup.
"""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

_SCRIPT = r'''
import unreal, json

TAG = "VERA_Vibe"
removed = []
warnings = []

def main():
    try:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    except Exception as e:
        print(json.dumps({"success": False, "error": "EditorActorSubsystem unavailable: %s" % e}))
        return

    try:
        actors = eas.get_all_level_actors()
    except Exception as e:
        print(json.dumps({"success": False, "error": "could not list level actors: %s" % e}))
        return

    targets = []
    for a in actors:
        try:
            if a.actor_has_tag(TAG):
                targets.append(a)
        except Exception:
            continue

    for a in targets:
        label = "<unknown>"
        try:
            label = a.get_actor_label()
        except Exception:
            pass
        try:
            eas.destroy_actor(a)
            removed.append(label)
        except Exception as e:
            warnings.append("could not remove %s: %s" % (label, e))

    out = {
        "success": True,
        "removed_count": len(removed),
        "removed": removed,
    }
    if warnings:
        out["warnings"] = warnings
    if not removed and not warnings:
        out["note"] = "no VERA vibe actors were present (level already clean)"
    print(json.dumps(out, indent=2))

try:
    main()
except Exception as e:
    print(json.dumps({"success": False, "error": "unexpected: %s" % e,
                      "removed": removed, "warnings": warnings}))
'''


class ClearVibeTool(Tool):
    name = "clear_vibe"
    description = (
        "Remove the cinematic vibe that set_vibe added to the open level, restoring it to "
        "its original look. Destroys every level actor tagged 'VERA_Vibe' (the DirectionalLight "
        "and unbound PostProcessVolume set_vibe spawned) and leaves everything else untouched. "
        "Idempotent — safe to call even if no vibe is active. USE THIS after you finish taking "
        "showcase screenshots/recordings to clean up. Reports how many actors were removed."
    )
    input_schema = {"type": "object", "properties": {}}
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        ctx.report("SceneVibe", "clearing VERA vibe actors from the open level")
        try:
            resp = send_json(ctx.bridge_port, {"script": _SCRIPT})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not reach the Unreal editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "Cleared the vibe.")
        return ToolResult(resp.get("error") or "editor script failed", is_error=True)
