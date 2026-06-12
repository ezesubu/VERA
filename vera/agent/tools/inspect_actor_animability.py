# vera/agent/tools/inspect_actor_animability.py
"""Percepción (read-only): ¿este actor es animable?

Devuelve si el actor es skeletal o static, qué skeleton usa y qué AnimSequences
compatibles existen en /Game (vía AssetRegistry — nada hardcodeado). Sin gate
destructivo: mirar no pide permiso.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import build_inspect_script, parse_json_output, tail_of_output
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class InspectActorAnimabilityTool(Tool):
    name = "inspect_actor_animability"
    description = (
        "Inspecciona (read-only) si un actor del nivel es animable: devuelve si es "
        "skeletal o static, qué skeleton usa y qué AnimSequences compatibles existen "
        "en el proyecto. Usala antes de animate_actor para saber qué es posible."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {
                "type": "string",
                "description": "label del actor en el nivel (match exacto o parcial)",
            },
        },
        "required": ["actor_name"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor_name = (args.get("actor_name") or "").strip()
        if not actor_name:
            return ToolResult("falta actor_name (label del actor a inspeccionar)",
                              is_error=True)
        ctx.report("InspectAnimability", f"diagnosticando {actor_name!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_inspect_script(actor_name)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"no se pudo inspeccionar el actor: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo al inspeccionar el actor",
                              is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable del editor:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        if data.get("error") == "not_found":
            cands = ", ".join(data.get("candidates") or []) or "(sin actores en el nivel)"
            return ToolResult(
                f"actor {actor_name!r} no encontrado; labels parecidos: {cands}",
                is_error=True)
        return ToolResult(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
