# vera/agent/tools/retarget_animations.py
"""Batch retarget: duplicates AnimSequences from the source skeleton to the target.

Find-first/idempotent: anims already retargeted (suffix _VERA_RTG in
<target mesh folder>/VERA_Retargeted/) are skipped, not duplicated.
Optionally plays the first one on an actor (closing the loop with phase 1:
afterwards use capture_actor to SEE the result).
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._retarget_scripts import build_retarget_batch_script
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class RetargetAnimationsTool(Tool):
    name = "retarget_animations"
    description = (
        "Retargets AnimSequences from the source skeleton to the target using an "
        "existing IK Retargeter (use ensure_retargeter first). 'auto' picks the "
        "basic locomotion set (idle/walk/jog, up to 5). Creates new assets "
        "(suffix _VERA_RTG) and optionally plays the first one on an actor. "
        "This is step 3 of retargeting. Requires confirmation."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "retargeter_path": {"type": "string",
                                "description": "/Game/... path of the IKRetargeter"},
            "animations": {
                "description": "'auto' (default) or a list of source AnimSequence names",
            },
            "target_actor_name": {"type": "string",
                                  "description": "level actor on which to play the result"},
            "play_first": {"type": "boolean",
                           "description": "play the first retargeted anim (requires target_actor_name)"},
        },
        "required": ["retargeter_path"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        rtg = (args.get("retargeter_path") or "").strip()
        if not rtg:
            return ToolResult("missing retargeter_path", is_error=True)
        animations = args.get("animations") or "auto"
        if not isinstance(animations, (str, list)):
            return ToolResult("animations must be 'auto' or a list of names",
                              is_error=True)
        if isinstance(animations, str) and animations != "auto":
            animations = [animations]
        target_actor = (args.get("target_actor_name") or "").strip() or None
        play_first = bool(args.get("play_first", False))
        if play_first and target_actor is None:
            return ToolResult("play_first requires target_actor_name", is_error=True)
        ctx.report("RetargetAnims", f"batch over {rtg!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_retarget_batch_script(
                rtg, animations, target_actor, play_first)})
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
