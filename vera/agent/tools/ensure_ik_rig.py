# vera/agent/tools/ensure_ik_rig.py
"""Find-first: garantiza que exista un IKRigDefinition para un esqueleto.

Si ya hay un rig para ese skeleton lo devuelve (created: false, idempotente);
si no, lo crea con auto-characterize. Si el esqueleto no coincide con ningún
template humanoide conocido, borra el asset a medio crear y reporta honesto.
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
        "Garantiza que exista un IK Rig para el esqueleto de un actor o "
        "SkeletalMesh (lo encuentra si ya existe, o lo crea con "
        "auto-characterize). Es el paso 1 del retargeting: usala antes de "
        "ensure_retargeter. Crea un asset: requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {"type": "string",
                           "description": "label de un actor skeletal del nivel"},
            "skeleton_path": {"type": "string",
                              "description": "path /Game/... de un SkeletalMesh o IKRig"},
        },
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor = (args.get("actor_name") or "").strip()
        skel = (args.get("skeleton_path") or "").strip()
        if bool(actor) == bool(skel):
            return ToolResult(
                "pasá exactamente una referencia: actor_name O skeleton_path",
                is_error=True)
        ref = actor or skel
        ctx.report("EnsureIKRig", f"resolviendo rig para {ref!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_ensure_rig_script(ref)})
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
