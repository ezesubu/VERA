# vera/agent/tools/ensure_ik_rig.py
"""Find-first: ensure an IKRigDefinition exists for a skeleton.

If a rig already exists for that skeleton it returns it (created: false,
idempotent); otherwise it creates one with auto-characterize. If the skeleton
matches no known humanoid template, it deletes the half-created asset and reports
honestly.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._retarget_scripts import build_ensure_rig_script
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class EnsureIKRigTool(Tool):
    name = "ensure_ik_rig"
    description = (
        "Ensures an IK Rig exists for the skeleton of an actor or "
        "SkeletalMesh (finds it if it already exists, or creates it with "
        "auto-characterize). This is step 1 of retargeting: use it before "
        "ensure_retargeter. Creates an asset: requires confirmation."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {"type": "string",
                           "description": "label of a skeletal actor in the level"},
            "skeleton_path": {"type": "string",
                              "description": "/Game/... path of a SkeletalMesh or IKRig"},
        },
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor = (args.get("actor_name") or "").strip()
        skel = (args.get("skeleton_path") or "").strip()
        if bool(actor) == bool(skel):
            return ToolResult(
                "pass exactly one reference: actor_name OR skeleton_path",
                is_error=True)
        ref = actor or skel
        ctx.report("EnsureIKRig", f"resolving rig for {ref!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_ensure_rig_script(ref)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge down: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "editor failure", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"unparseable response:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        return ToolResult(rendered, is_error=bool(data.get("error")))
