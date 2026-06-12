# vera/agent/tools/capture_actor.py
"""Percepción visual (read-only): el cerebro VE un actor aislado.

"A por fuera, C por dentro": una sola llamada con restore garantizado; adentro
scripts separados setup/frame/restore orquestados acá. El restore viaja en un
finally del lado cliente: aunque un frame falle, el nivel vuelve a su estado.
Captura vía SceneCapture2D (render a demanda, funciona con el editor minimizado);
aislamiento por lista show-only — el nivel no se toca.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid

from vera.agent.tool import Tool, ToolContext, ToolResult, image_block
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._capture_scripts import (
    build_setup_script, build_pose_script, build_capture_script,
    build_restore_script)
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

MAX_FRAMES = 6
FILE_TIMEOUT_S = 15.0
POLL_INTERVAL_S = 0.3
# tras el scrub, el editor necesita tickear (~60fps visible) para evaluar la
# pose ANTES de capturar; sin esta espera la captura ve la pose anterior
POSE_SETTLE_S = 0.25


class CaptureActorTool(Tool):
    name = "capture_actor"
    description = (
        "Percepción visual (read-only): aísla un actor del nivel (oculta el "
        "resto, fondo neutro) y captura N frames a 640x360 que te llegan como "
        "imágenes — usala para VER un actor o juzgar una animación. "
        "mode=anim recorre una animación en N tiempos (requiere skeletal); "
        "mode=orbit lo rodea en N ángulos (cualquier actor). Restaura el nivel "
        "automáticamente al terminar."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {
                "type": "string",
                "description": "label del actor (match exacto o parcial)",
            },
            "mode": {
                "type": "string", "enum": ["anim", "orbit"],
                "description": "default: anim si hay animation, sino orbit",
            },
            "animation": {
                "type": "string",
                "description": "solo mode=anim: 'auto' o nombre de AnimSequence",
            },
            "frames": {
                "type": "integer", "minimum": 1, "maximum": 6,
                "description": "cantidad de capturas (default 4)",
            },
        },
        "required": ["actor_name"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor_name = (args.get("actor_name") or "").strip()
        if not actor_name:
            return ToolResult("falta actor_name (label del actor)", is_error=True)
        try:
            frames = int(args.get("frames", 4))
        except (TypeError, ValueError):
            return ToolResult("frames debe ser un entero entre 1 y 6", is_error=True)
        if not 1 <= frames <= MAX_FRAMES:
            return ToolResult("frames debe estar entre 1 y 6", is_error=True)
        animation = args.get("animation")
        mode = args.get("mode") or ("anim" if animation else "orbit")
        if mode not in ("anim", "orbit"):
            return ToolResult(f"mode inválido: {mode!r} (anim|orbit)", is_error=True)
        if mode == "orbit" and animation:
            return ToolResult("animation solo aplica a mode=anim", is_error=True)
        if mode == "anim" and not animation:
            animation = "auto"

        ctx.report("CaptureActor", f"aislando {actor_name!r} ({mode}, {frames} frames)")
        setup = self._send(ctx, build_setup_script(
            actor_name, animation if mode == "anim" else None))
        if isinstance(setup, ToolResult):
            return setup
        if setup.get("error"):
            # los errores del setup ocurren ANTES de mutar el nivel: sin restore
            return ToolResult(
                json.dumps(setup, ensure_ascii=False, sort_keys=True), is_error=True)

        warnings = []
        if mode == "anim":
            length = float(setup.get("anim_length") or 0.0)
            if length <= 0.0:
                # el setup YA mutó el nivel: hay que pasar por el restore igual
                values = []
                warnings.append(
                    f"anim_length inválida ({length}): nada para scrubear")
            else:
                values = [round((i + 0.5) / frames * length, 3)
                          for i in range(frames)]
        else:
            values = [round(360.0 * i / frames, 1) for i in range(frames)]

        nonce = uuid.uuid4().hex[:8]
        shot_dir = setup.get("screenshot_dir") or ""
        files, images = [], []
        try:
            for i, value in enumerate(values):
                fname = f"vera_cap_{nonce}_{i}.png"
                ctx.report("CaptureActor", f"frame {i + 1}/{len(values)}")
                # pose y captura en round-trips separados: el editor evalua la
                # pose entre mensajes; capturar en el mismo call stack veria
                # la pose anterior (off-by-one, hallado en E2E vivo)
                pose = self._send(ctx, build_pose_script(mode, value))
                if isinstance(pose, ToolResult):
                    warnings.append(f"frame {i} (pose): {pose.content}")
                    break
                if pose.get("error"):
                    warnings.append(f"frame {i} (pose): {pose['error']}")
                    break
                if mode == "anim":
                    time.sleep(POSE_SETTLE_S)
                frame = self._send(ctx, build_capture_script(fname))
                if isinstance(frame, ToolResult):
                    warnings.append(f"frame {i}: {frame.content}")
                    break
                if frame.get("error"):
                    warnings.append(f"frame {i}: {frame['error']}")
                    break
                path = os.path.join(shot_dir, fname)
                data = self._wait_for_file(path)
                if data is None:
                    warnings.append(f"frame {i}: timeout esperando {fname}")
                    break
                files.append(path)
                images.append(image_block(base64.b64encode(data).decode("ascii")))
        finally:
            restore_info = self._restore(ctx)

        meta = {
            "actor": setup.get("actor"), "mode": mode,
            "frames_capturados": len(images), "files": files,
            "isolation": setup.get("isolation"),
            "restored": bool(restore_info.get("restored")),
        }
        if mode == "anim":
            meta["animation"] = setup.get("animation")
            meta["anim_length"] = setup.get("anim_length")
            meta["times"] = values[: len(images)]
        else:
            meta["angles"] = values[: len(images)]
        if warnings:
            meta["warnings"] = warnings
        if not restore_info.get("restored"):
            meta["restore_detail"] = restore_info

        text = json.dumps(meta, ensure_ascii=False, sort_keys=True)
        if not images:
            return ToolResult(text, is_error=True)
        return ToolResult([{"type": "text", "text": text}] + images)

    # ---- helpers ----

    def _send(self, ctx: ToolContext, script: str):
        """Un round-trip por el bridge: dict parseado o ToolResult de error."""
        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge caído: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo en el editor", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        return data

    def _restore(self, ctx: ToolContext) -> dict:
        """Best-effort y nunca lanza: el finally no debe enmascarar el error real."""
        try:
            data = self._send(ctx, build_restore_script())
        except Exception as e:  # noqa: BLE001
            return {"restored": False, "reason": str(e)}
        if isinstance(data, ToolResult):
            return {"restored": False, "reason": str(data.content)}
        if data.get("reason") == "no_state":
            # setup nunca llegó a mutar: no había nada que restaurar
            return {"restored": True, "reason": "no_state"}
        return data

    def _wait_for_file(self, path: str, timeout=None, interval=None):
        """Espera a que el PNG exista con tamaño estable. bytes o None.
        Lee los límites del módulo en runtime para que los tests los achiquen."""
        timeout = FILE_TIMEOUT_S if timeout is None else timeout
        interval = POLL_INTERVAL_S if interval is None else interval
        deadline = time.monotonic() + timeout
        last = -1
        while time.monotonic() < deadline:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            if size > 0 and size == last:
                with open(path, "rb") as f:
                    return f.read()
            last = size
            time.sleep(interval)
        return None
