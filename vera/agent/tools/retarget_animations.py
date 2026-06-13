# vera/agent/tools/retarget_animations.py
"""Batch retarget: duplica AnimSequences del skeleton source al target.

Find-first/idempotente: las anims ya retargeteadas (sufijo _VERA_RTG en
<carpeta del mesh target>/VERA_Retargeted/) se saltean, no se duplican.
Opcionalmente reproduce la primera en un actor (cerrando el loop con fase 1:
después usá capture_actor para VER el resultado).
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
        "Retargetea AnimSequences del esqueleto source al target usando un IK "
        "Retargeter existente (usá ensure_retargeter antes). 'auto' elige el "
        "set básico de locomoción (idle/walk/jog, hasta 5). Crea assets nuevos "
        "(sufijo _VERA_RTG) y opcionalmente reproduce el primero en un actor. "
        "Es el paso 3 del retargeting. Requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "retargeter_path": {"type": "string",
                                "description": "path /Game/... del IKRetargeter"},
            "animations": {
                "description": "'auto' (default) o lista de nombres de AnimSequence del source",
            },
            "target_actor_name": {"type": "string",
                                  "description": "actor del nivel donde reproducir el resultado"},
            "play_first": {"type": "boolean",
                           "description": "reproducir la primera anim retargeteada (requiere target_actor_name)"},
        },
        "required": ["retargeter_path"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        rtg = (args.get("retargeter_path") or "").strip()
        if not rtg:
            return ToolResult("falta retargeter_path", is_error=True)
        animations = args.get("animations") or "auto"
        if not isinstance(animations, (str, list)):
            return ToolResult("animations debe ser 'auto' o una lista de nombres",
                              is_error=True)
        if isinstance(animations, str) and animations != "auto":
            animations = [animations]
        target_actor = (args.get("target_actor_name") or "").strip() or None
        play_first = bool(args.get("play_first", False))
        if play_first and target_actor is None:
            return ToolResult("play_first requiere target_actor_name", is_error=True)
        ctx.report("RetargetAnims", f"batch sobre {rtg!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_retarget_batch_script(
                rtg, animations, target_actor, play_first)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge caído: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo en el editor", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        return ToolResult(rendered, is_error=bool(data.get("error")))
