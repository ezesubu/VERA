# vera/agent/tools/animate_actor.py
"""Action (destructive): animate an existing actor or spawn an animated Manny.

- animate: re-diagnoses the actor inside the script (safeguard) and picks a
  strategy: play_animation (skeletal with compatible anims), procedural movement
  (static + allow_procedural=true), or an honest not_animable report
  (valid result, NOT an error).
- spawn: SkeletalMeshActor with SKM_Manny_Simple, tagged VERA_SPAWNED,
  by default in front of the editor camera, dropped to the floor by line trace.
- stop: stops whatever VERA set in motion — the procedural tick (restoring the
  original position and rotation) and/or the single-node playback (returning
  control to the AnimBlueprint if the component has one).

Error rule: is_error=True only if the system failed or the request was
impossible WITH no effects (data has "error" and NO strategy_used). If the
spawn happened but the requested anim was not compatible, the result comes back
complete with the detail — the brain decides how to proceed.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import (
    build_animate_script, build_spawn_script, build_stop_script,
    parse_json_output, tail_of_output)
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class AnimateActorTool(Tool):
    name = "animate_actor"
    description = (
        "Animates a level actor (action=animate) or spawns an animated Manny "
        "character (action=spawn), or stops an animation VERA started "
        "(action=stop: halts the procedural movement, restoring the original pose, "
        "and returns control to the AnimBlueprint). Skeletal: plays a "
        "compatible AnimSequence ('auto' picks idle/walk). Static: procedural "
        "movement only if allow_procedural=true; otherwise it explains why it is "
        "not animatable. Modifies the level: requires confirmation."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["animate", "spawn", "stop"]},
            "actor_name": {
                "type": "string",
                "description": "actor label (required if action=animate or stop)",
            },
            "animation": {
                "type": "string",
                "description": "'auto' (default) or the name of a compatible AnimSequence",
            },
            "looping": {
                "type": "boolean",
                "description": "play in a loop (default true)",
            },
            "location": {
                "type": "array", "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "spawn: [x,y,z]; default in front of the editor camera",
            },
            "allow_procedural": {
                "type": "boolean",
                "description": "allow rotation/bobbing fallback on static meshes",
            },
        },
        "required": ["action"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        action = args.get("action")
        animation = (args.get("animation") or "auto").strip() or "auto"
        looping = bool(args.get("looping", True))

        if action == "animate":
            actor_name = (args.get("actor_name") or "").strip()
            if not actor_name:
                return ToolResult("action=animate requires actor_name", is_error=True)
            ctx.report("AnimateActor", f"animating {actor_name!r} ({animation})")
            script = build_animate_script(
                actor_name, animation, looping,
                bool(args.get("allow_procedural", False)))
        elif action == "spawn":
            location = args.get("location")
            if location is not None and (
                    not isinstance(location, (list, tuple)) or len(location) != 3):
                return ToolResult("location must be [x, y, z]", is_error=True)
            ctx.report("AnimateActor", f"spawning animated Manny ({animation})")
            script = build_spawn_script(animation, looping, location)
        elif action == "stop":
            actor_name = (args.get("actor_name") or "").strip()
            if not actor_name:
                return ToolResult("action=stop requires actor_name", is_error=True)
            ctx.report("AnimateActor", f"stopping animation of {actor_name!r}")
            script = build_stop_script(actor_name)
        else:
            return ToolResult(
                f"invalid action: {action!r} (use 'animate', 'spawn' or 'stop')",
                is_error=True)

        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"could not run in the editor: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "failed to animate", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"unparseable response from the editor:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        if data.get("error") and not data.get("strategy_used"):
            return ToolResult(rendered, is_error=True)
        return ToolResult(rendered)
