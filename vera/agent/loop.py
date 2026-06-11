"""AgentLoop: bucle de tool-use de VERA sobre la Messages API de Anthropic."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from vera.agent.tool import ToolContext, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"
MAX_ITERATIONS = 20
MAX_TOOL_RESULT_CHARS = 20_000  # un log gigante no debe inflar el contexto sin control


def _final_text(content) -> str:
    parts = [b.text for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(parts) if parts else "(sin texto)"


def _tool_result(tool_use_id: str, content, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


class AgentLoop:
    """Corre el bucle: el modelo razona → elige tools → ve resultados → repite.

    `llm_client` es un cliente con forma de `anthropic.Anthropic`
    (`.messages.stream(...)`), inyectable para tests.
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

    def run(
        self,
        command: str,
        emit: Optional[Callable[[dict], None]] = None,
        *,
        messages: Optional[list] = None,
        confirm: Optional[Callable] = None,
    ) -> dict:
        """`messages`: historial externo (lo muta in place — lo posee la Session).
        `confirm`: override por-comando del gate destructivo (p.ej. el round-trip
        a la UI de la conexión en curso)."""
        ctx = ToolContext(bridge_port=self.bridge_port, emit=emit, llm=self.llm)
        confirm = confirm if confirm is not None else self.confirm
        if messages is None:
            messages = []
        messages.append({"role": "user", "content": command})
        tools = self.registry.to_anthropic()

        for _ in range(MAX_ITERATIONS):
            try:
                resp = self._call_llm(messages, tools, emit)
            except Exception as e:  # APIError, timeout, red caída: cerrar el contrato igual
                logger.exception("[AgentLoop] error de comunicación con el modelo")
                msg = f"error de comunicación con el modelo: {e}"
                if emit:
                    emit({"type": "final", "status": "error", "msg": msg})
                return {"status": "error", "msg": msg}

            if resp.stop_reason == "end_turn":
                messages.append({"role": "assistant", "content": resp.content})
                text = _final_text(resp.content)
                if emit:
                    emit({"type": "final", "status": "success", "msg": text})
                return {"status": "success", "msg": text}

            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue

            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                # SECUENCIAL a propósito: cada tool destructiva hace un round-trip
                # de confirmación por el MISMO socket; paralelizar esto mezclaría
                # las respuestas del gate. No convertir en concurrent/gather.
                results = [
                    self._run_tool(block, ctx, emit, confirm)
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

    def _run_tool(self, block, ctx: ToolContext, emit, confirm) -> dict:
        tool = self.registry.get(block.name)
        if tool is None:
            return _tool_result(block.id, f"tool desconocida: {block.name}", True)
        if emit:
            emit({"type": "tool_use", "agent": tool.name, "input": block.input})
        if tool.destructive and confirm and not confirm(tool, block.input):
            return _tool_result(block.id, "El usuario rechazó la acción.", True)
        try:
            result = tool.execute(block.input, ctx)
        except Exception as e:  # una tool rota nunca tumba el loop
            logger.exception("[AgentLoop] la tool %s lanzó excepción", tool.name)
            result = ToolResult(f"excepción en la tool: {e}", is_error=True)
        if isinstance(result.content, str) and len(result.content) > MAX_TOOL_RESULT_CHARS:
            marca = f"\n[...resultado truncado: {len(result.content)} caracteres en total]"
            result = ToolResult(
                result.content[: MAX_TOOL_RESULT_CHARS - len(marca)] + marca,
                is_error=result.is_error,
            )
        if emit:
            emit({"type": "tool_result", "agent": tool.name, "is_error": result.is_error})
        return _tool_result(block.id, result.content, result.is_error)

    def _call_llm(self, messages, tools, emit):
        """Una llamada streaming al modelo. Emite los deltas de thinking al
        timeline (en claude-opus-4-8 el thinking viene omitido salvo que se
        pida display=summarized). El texto NO se emite por delta: el evento
        `final` ya pinta la respuesta completa."""
        with self.llm.messages.stream(
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive", "display": "summarized"},
            system=self.system,
            tools=tools,
            messages=messages,
        ) as stream:
            for event in stream:
                if (
                    emit
                    and getattr(event, "type", None) == "content_block_delta"
                    and getattr(getattr(event, "delta", None), "type", None) == "thinking_delta"
                    and event.delta.thinking
                ):
                    emit({"type": "thinking", "msg": event.delta.thinking})
            return stream.get_final_message()
