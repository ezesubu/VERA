"""Contrato de herramientas del cerebro de VERA."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ToolResult:
    """Resultado de ejecutar una tool. `content` vuelve al modelo.

    `content` puede ser un string (texto plano) o una lista de content blocks
    de la API — p.ej. texto + imagen para tools de percepción (ver `image_block`).
    """
    content: Any
    is_error: bool = False


def image_block(data_b64: str, media_type: str = "image/png") -> dict:
    """Content block de imagen (base64) para devolver en un ToolResult."""
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data_b64},
    }


@dataclass
class ToolContext:
    """Servicios que el AgentLoop le pasa a cada tool en execute()."""
    bridge_port: int = 9878
    emit: Optional[Callable[[dict], None]] = None  # emisor de eventos a la UI
    llm: Any = None                                 # cliente LLM para sub-llamadas

    def report(self, agent: str, msg: str) -> None:
        """Emite un evento de progreso si hay canal conectado (best-effort)."""
        if self.emit:
            self.emit({"type": "progress", "agent": agent, "msg": msg})


class Tool:
    """Clase base de toda herramienta. Subclasealá y definí los atributos.

    Un contribuidor agrega una capacidad creando un archivo en
    vera/agent/tools/ con una subclase de Tool — el ToolRegistry la descubre.
    """
    name: str = ""
    description: str = ""           # qué hace + CUÁNDO usarla (lo lee el modelo)
    input_schema: dict = {}         # JSON Schema de los argumentos
    destructive: bool = False       # ¿requiere confirmación? (irreversible)

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def to_anthropic(self) -> dict:
        """Forma que espera el parámetro `tools` de la Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
