"""Construcción del AgentLoop de producción."""
from __future__ import annotations

from vera.agent.loop import AgentLoop, DEFAULT_MODEL
from vera.agent.registry import ToolRegistry

SYSTEM_PROMPT = (
    "Sos VERA, un ingeniero técnico autónomo de Unreal Engine. "
    "Trabajás dentro del editor del usuario a través de herramientas. "
    "Pensá tu plan, usá las herramientas necesarias, verificá los resultados "
    "y corregí si algo falla. Para cualquier operación sin tool dedicada, "
    "escribí código con `run_ue_python` (el módulo `unreal` está disponible; "
    "usá print() para devolver datos). Sé conciso en tu respuesta final."
)


def build_agent_loop(llm_client, *, model: str = DEFAULT_MODEL, confirm=None) -> AgentLoop:
    """Arma un AgentLoop con todas las tools auto-descubiertas de vera/agent/tools/."""
    import vera.agent.tools as tools_pkg

    registry = ToolRegistry()
    registry.discover(tools_pkg)
    return AgentLoop(
        registry,
        llm_client,
        model=model,
        system=SYSTEM_PROMPT,
        confirm=confirm,
    )
