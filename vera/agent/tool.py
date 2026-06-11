"""Contrato de herramientas del cerebro de VERA."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ToolResult:
    """Resultado de ejecutar una tool. `content` vuelve al modelo."""
    content: str
    is_error: bool = False


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
