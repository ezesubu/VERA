"""AgentLoop: bucle de tool-use de VERA sobre la Messages API de Anthropic."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from vera.agent.tool import ToolContext, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"
MAX_ITERATIONS = 20


def _final_text(content) -> str:
    parts = [b.text for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(parts) if parts else "(sin texto)"


def _tool_result(tool_use_id: str, content: str, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


class AgentLoop:
    """Corre el bucle: el modelo razona → elige tools → ve resultados → repite.

    `llm_client` es un cliente con forma de `anthropic.Anthropic`
    (`.messages.create(...)`), inyectable para tests.
    `confirm(tool, args) -> bool` gatea tools destructivas; None = sin gate.
    """

    def __init__(
        self,
        registry,
        llm_client,
        *,
        model: str = DEFAULT_MODEL,
        system: str = "",
        bridge_port: int = 9878,
        confirm: Optional[Callable] = None,
    ) -> None:
        self.registry = registry
        self.llm = llm_client
        self.model = model
        self.system = system
        self.bridge_port = bridge_port
        self.confirm = confirm

    def run(self, command: str, emit: Optional[Callable[[dict], None]] = None) -> dict:
        ctx = ToolContext(bridge_port=self.bridge_port, emit=emit, llm=self.llm)
        messages = [{"role": "user", "content": command}]
        tools = self.registry.to_anthropic()

        for _ in range(MAX_ITERATIONS):
            resp = self.llm.messages.create(
                model=self.model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=self.system,
                tools=tools,
                messages=messages,
            )

            if resp.stop_reason == "end_turn":
                text = _final_text(resp.content)
                if emit:
                    emit({"type": "final", "status": "success", "msg": text})
                return {"status": "success", "msg": text}

            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue

            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = [
                    self._run_tool(block, ctx, emit)
                    for block in resp.content
                    if getattr(block, "type", None) == "tool_use"
                ]
                if not results:  # nunca appendear content:[] — rompe la API con 400
                    msg = "stop_reason tool_use sin bloques tool_use en el contenido"
                    if emit:
                        emit({"type": "final", "status": "error", "msg": msg})
                    return {"status": "error", "msg": msg}
                messages.append({"role": "user", "content": results})
                continue

            # max_tokens, refusal, stop_sequence o valores futuros: cortar limpio.
            # Nunca appendear un mensaje user vacío — la API lo rechaza con 400.
            msg = f"el modelo se detuvo de forma inesperada ({resp.stop_reason})"
            if emit:
                emit({"type": "final", "status": "error", "msg": msg})
            return {"status": "error", "msg": msg}

        if emit:
            emit({"type": "final", "status": "error", "msg": "límite de iteraciones"})
        return {"status": "error", "msg": "límite de iteraciones alcanzado"}

    def _run_tool(self, block, ctx: ToolContext, emit) -> dict:
        tool = self.registry.get(block.name)
        if tool is None:
            return _tool_result(block.id, f"tool desconocida: {block.name}", True)
        if emit:
            emit({"type": "tool_use", "agent": tool.name, "input": block.input})
        if tool.destructive and self.confirm and not self.confirm(tool, block.input):
            return _tool_result(block.id, "El usuario rechazó la acción.", True)
        try:
            result = tool.execute(block.input, ctx)
        except Exception as e:  # una tool rota nunca tumba el loop
            logger.exception("[AgentLoop] la tool %s lanzó excepción", tool.name)
            result = ToolResult(f"excepción en la tool: {e}", is_error=True)
        if emit:
            emit({"type": "tool_result", "agent": tool.name, "is_error": result.is_error})
        return _tool_result(block.id, result.content, result.is_error)
