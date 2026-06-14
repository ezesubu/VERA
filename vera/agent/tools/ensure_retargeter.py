# vera/agent/tools/ensure_retargeter.py
"""Find-first: ensure an IKRetargeter source→target exists.

Requires that BOTH IK Rigs exist (one gate per asset: if one is missing, the
error points to ensure_ik_rig — it does not create it implicitly). The chain
mapping goes in the output so the brain can judge the quality BEFORE spending the
batch.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._retarget_scripts import build_ensure_retargeter_script
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class EnsureRetargeterTool(Tool):
    name = "ensure_retargeter"
    description = (
        "Ensures an IK Retargeter from the source skeleton to the target exists "
        "(finds it or creates it with fuzzy auto-mapping of chains). Requires "
        "both IK Rigs to exist (use ensure_ik_rig first). Returns the chain "
        "mapping so you can evaluate its quality. This is step 2 of retargeting. "
        "Creates an asset: requires confirmation."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string",
                       "description": "where to copy the animation from: actor label or SkeletalMesh/IKRig path"},
            "target": {"type": "string",
                       "description": "where to: actor label or SkeletalMesh/IKRig path"},
        },
        "required": ["source", "target"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        source = (args.get("source") or "").strip()
        target = (args.get("target") or "").strip()
        if not source or not target:
            return ToolResult("source and target are required", is_error=True)
        ctx.report("EnsureRetargeter", f"{source!r} -> {target!r}")
        try:
            resp = send_json(ctx.bridge_port,
                             {"script": build_ensure_retargeter_script(source, target)})
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
