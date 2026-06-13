# vera/agent/tools/ensure_retargeter.py
"""Find-first: garantiza que exista un IKRetargeter source→target.

Requiere que AMBOS IK Rigs existan (un gate por asset: si falta uno, el error
apunta a ensure_ik_rig — no lo crea implícitamente). El chain mapping va en el
output para que el cerebro juzgue la calidad ANTES de gastar el batch.
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
        "Garantiza que exista un IK Retargeter del esqueleto source al target "
        "(lo encuentra o lo crea con auto-mapeo fuzzy de chains). Requiere que "
        "ambos IK Rigs existan (usá ensure_ik_rig antes). Devuelve el chain "
        "mapping para que evalúes su calidad. Es el paso 2 del retargeting. "
        "Crea un asset: requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string",
                       "description": "de dónde copiar la animación: label de actor o path de SkeletalMesh/IKRig"},
            "target": {"type": "string",
                       "description": "hacia dónde: label de actor o path de SkeletalMesh/IKRig"},
        },
        "required": ["source", "target"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        source = (args.get("source") or "").strip()
        target = (args.get("target") or "").strip()
        if not source or not target:
            return ToolResult("source y target son requeridos", is_error=True)
        ctx.report("EnsureRetargeter", f"{source!r} -> {target!r}")
        try:
            resp = send_json(ctx.bridge_port,
                             {"script": build_ensure_retargeter_script(source, target)})
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
