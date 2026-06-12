# vera/agent/tools/animate_actor.py
"""Acción (destructiva): animar un actor existente o spawnear un Manny animado.

- animate: re-diagnostica el actor dentro del script (safeguard) y elige
  estrategia: play_animation (skeletal con anims compatibles), movimiento
  procedural (static + allow_procedural=true), o reporte honesto not_animable
  (resultado válido, NO error).
- spawn: SkeletalMeshActor con SKM_Manny_Simple, taggeado VERA_SPAWNED,
  default frente a la cámara del editor, aterrizado al piso por line trace.
- stop: detiene lo que VERA puso en movimiento — el tick procedural (restaurando
  posición y rotación originales) y/o el playback single-node (devolviendo el
  control al AnimBlueprint si el componente tiene uno).

Regla de error: is_error=True solo si el sistema falló o el pedido fue
imposible SIN efectos (data tiene "error" y NO tiene strategy_used). Si el
spawn ocurrió pero la anim pedida no era compatible, el resultado vuelve
completo con el detalle — el cerebro decide cómo seguir.
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
        "Anima un actor del nivel (action=animate) o spawnea un personaje Manny "
        "animado (action=spawn), o detiene una animación que VERA inició "
        "(action=stop: corta el movimiento procedural restaurando la pose original "
        "y devuelve el control al AnimBlueprint). Skeletal: reproduce una "
        "AnimSequence compatible ('auto' elige idle/walk). Static: solo movimiento "
        "procedural si allow_procedural=true; si no, explica por qué no es "
        "animable. Modifica el nivel: requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["animate", "spawn", "stop"]},
            "actor_name": {
                "type": "string",
                "description": "label del actor (requerido si action=animate o stop)",
            },
            "animation": {
                "type": "string",
                "description": "'auto' (default) o nombre de una AnimSequence compatible",
            },
            "looping": {
                "type": "boolean",
                "description": "reproducir en loop (default true)",
            },
            "location": {
                "type": "array", "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "spawn: [x,y,z]; default frente a la cámara del editor",
            },
            "allow_procedural": {
                "type": "boolean",
                "description": "permitir fallback rotación/bobbing en static meshes",
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
                return ToolResult("action=animate requiere actor_name", is_error=True)
            ctx.report("AnimateActor", f"animando {actor_name!r} ({animation})")
            script = build_animate_script(
                actor_name, animation, looping,
                bool(args.get("allow_procedural", False)))
        elif action == "spawn":
            location = args.get("location")
            if location is not None and (
                    not isinstance(location, (list, tuple)) or len(location) != 3):
                return ToolResult("location debe ser [x, y, z]", is_error=True)
            ctx.report("AnimateActor", f"spawneando Manny animado ({animation})")
            script = build_spawn_script(animation, looping, location)
        elif action == "stop":
            actor_name = (args.get("actor_name") or "").strip()
            if not actor_name:
                return ToolResult("action=stop requiere actor_name", is_error=True)
            ctx.report("AnimateActor", f"deteniendo animación de {actor_name!r}")
            script = build_stop_script(actor_name)
        else:
            return ToolResult(
                f"action inválida: {action!r} (usar 'animate', 'spawn' o 'stop')",
                is_error=True)

        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"no se pudo ejecutar en el editor: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo al animar", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable del editor:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        if data.get("error") and not data.get("strategy_used"):
            return ToolResult(rendered, is_error=True)
        return ToolResult(rendered)
