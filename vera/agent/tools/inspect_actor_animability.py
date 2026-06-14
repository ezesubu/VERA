# vera/agent/tools/inspect_actor_animability.py
"""Perception (read-only): is this actor animatable?

Returns whether the actor is skeletal or static, which skeleton it uses, and
which compatible AnimSequences exist in /Game (via AssetRegistry — nothing
hardcoded). No destructive gate: looking does not ask for permission.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import build_inspect_script, parse_json_output, tail_of_output
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class InspectActorAnimabilityTool(Tool):
    name = "inspect_actor_animability"
    description = (
        "Inspects (read-only) whether a level actor is animatable: returns whether "
        "it is skeletal or static, which skeleton it uses, and which compatible "
        "AnimSequences exist in the project. Use it before animate_actor to know what is possible."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {
                "type": "string",
                "description": "actor label in the level (exact or partial match)",
            },
        },
        "required": ["actor_name"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor_name = (args.get("actor_name") or "").strip()
        if not actor_name:
            return ToolResult("missing actor_name (label of the actor to inspect)",
                              is_error=True)
        ctx.report("InspectAnimability", f"diagnosing {actor_name!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_inspect_script(actor_name)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"could not inspect the actor: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "failed to inspect the actor",
                              is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"unparseable response from the editor:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        if data.get("error") == "not_found":
            cands = ", ".join(data.get("candidates") or []) or "(no actors in the level)"
            return ToolResult(
                f"actor {actor_name!r} not found; similar labels: {cands}",
                is_error=True)
        return ToolResult(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
