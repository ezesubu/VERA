"""Capa 0 (bash-core): ejecutar Python arbitrario dentro del editor de UE."""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class RunUEPythonTool(Tool):
    name = "run_ue_python"
    description = (
        "Ejecuta código Python dentro del editor de Unreal Engine (main-thread safe) "
        "vía el bridge. Usá esto para CUALQUIER operación en el editor que no tenga una "
        "tool dedicada: crear/modificar actors, leer el nivel, ajustar settings, etc. "
        "El módulo `unreal` ya está disponible. Usá print() para devolver datos."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Código Python a ejecutar en el editor.",
            }
        },
        "required": ["code"],
    }
    destructive = True  # Decisión MVP: destructiva por defecto (pide OK siempre)

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        code = (args.get("code") or "").strip()
        if not code:
            return ToolResult("Error: el argumento 'code' está vacío.", is_error=True)
        ctx.report("UEPython", "ejecutando script en el editor")
        try:
            resp = send_json(ctx.bridge_port, {"script": code})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"No se pudo ejecutar en el editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "(sin salida)")
        return ToolResult(resp.get("error") or "fallo desconocido en el editor", is_error=True)
