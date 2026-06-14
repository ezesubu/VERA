"""AgentLoop: VERA's tool-use loop over the Anthropic Messages API."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from vera.agent.tool import ToolContext, ToolResult, image_block

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"
MAX_ITERATIONS = 20
MAX_TOOL_RESULT_CHARS = 20_000  # a giant log must not bloat the context unchecked


def _final_text(content) -> str:
    parts = [b.text for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(parts) if parts else "(no text)"


def _tool_result(tool_use_id: str, content, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


class AgentLoop:
    """Runs the loop: the model reasons → picks tools → sees results → repeats.

    `llm_client` is a client shaped like `anthropic.Anthropic`
    (`.messages.stream(...)`), injectable for tests.
    `confirm(tool, args) -> bool` gates destructive tools; None = no gate.
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
        compact: bool = False,
    ) -> None:
        self.registry = registry
        self.llm = llm_client
        self.model = model
        self.system = system
        self.bridge_port = bridge_port
        self.confirm = confirm
        self.compact = compact

    def run(
        self,
        command: str,
        emit: Optional[Callable[[dict], None]] = None,
        *,
        messages: Optional[list] = None,
        confirm: Optional[Callable] = None,
        include_destructive: bool = True,
        should_stop: Optional[Callable[[], bool]] = None,
        image: Optional[dict] = None,
    ) -> dict:
        """`messages`: external history (mutated in place — owned by the Session).
        `confirm`: per-command override of the destructive gate (e.g. the round-trip
        to the UI over the live connection).
        `include_destructive`: if False, `destructive` tools are EXCLUDED from the
        schema the model sees (readonly / "just plan this time" mode). The model
        never sees them, so it cannot invoke them.
        `should_stop`: cooperative cancellation callback. Checked BETWEEN
        iterations (before calling the model and before running the tools);
        if it returns True the loop exits cleanly with status "stopped". The
        in-flight command (a model call or a tool already started) finishes; the
        cut is between steps, not abortive.
        `image`: optional attached image `{"data": "<base64>", "media_type":
        "image/png"|"image/jpeg"}`. When present, the user turn starts as a list of
        content blocks (text + image, Anthropic shape) so the model SEES it.
        Without an image the content stays the plain string as always."""
        ctx = ToolContext(bridge_port=self.bridge_port, emit=emit, llm=self.llm)
        confirm = confirm if confirm is not None else self.confirm
        if messages is None:
            messages = []
        if image:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": command},
                image_block(image["data"], image["media_type"]),
            ]})
        else:
            messages.append({"role": "user", "content": command})
        if include_destructive:
            tools = self.registry.to_anthropic(compact=self.compact)
        else:
            tools = [
                t.to_anthropic(compact=self.compact)
                for t in self.registry.all()
                if not t.destructive
            ]

        for _ in range(MAX_ITERATIONS):
            if should_stop and should_stop():
                return self._stopped(emit)
            try:
                resp = self._call_llm(messages, tools, emit)
            except Exception as e:  # APIError, timeout, connection dropped: close the contract anyway
                logger.exception("[AgentLoop] error communicating with the model")
                msg = f"error communicating with the model: {e}"
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
                if should_stop and should_stop():
                    return self._stopped(emit)
                # Surface the model's narration ("I'll do X…") that comes alongside
                # the tool calls, so the user sees WHAT VERA is doing — not just thinking.
                if emit:
                    for block in resp.content:
                        if getattr(block, "type", None) == "text" and (block.text or "").strip():
                            emit({"type": "say", "msg": block.text})
                # SEQUENTIAL on purpose: each destructive tool does a confirmation
                # round-trip over the SAME socket; parallelizing this would mix up
                # the gate responses. Do not turn into concurrent/gather.
                results = [
                    self._run_tool(block, ctx, emit, confirm)
                    for block in resp.content
                    if getattr(block, "type", None) == "tool_use"
                ]
                if not results:  # never append content:[] — breaks the API with a 400
                    msg = "stop_reason tool_use with no tool_use blocks in the content"
                    if emit:
                        emit({"type": "final", "status": "error", "msg": msg})
                    return {"status": "error", "msg": msg}
                messages.append({"role": "user", "content": results})
                continue

            # max_tokens, refusal, stop_sequence or future values: cut cleanly.
            # Never append an empty user message — the API rejects it with a 400.
            msg = f"the model stopped unexpectedly ({resp.stop_reason})"
            if emit:
                emit({"type": "final", "status": "error", "msg": msg})
            return {"status": "error", "msg": msg}

        if emit:
            emit({"type": "final", "status": "error", "msg": "iteration limit"})
        return {"status": "error", "msg": "iteration limit reached"}

    @staticmethod
    def _stopped(emit) -> dict:
        """Cooperative cancellation by the user. `stopped` is a new terminal
        status, alongside success/error."""
        if emit:
            emit({"type": "final", "status": "stopped", "msg": "Stopped by the user."})
        return {"status": "stopped", "msg": "stopped by user"}

    def _run_tool(self, block, ctx: ToolContext, emit, confirm) -> dict:
        tool = self.registry.get(block.name)
        if tool is None:
            return _tool_result(block.id, f"unknown tool: {block.name}", True)
        if emit:
            emit({"type": "tool_use", "agent": tool.name, "input": block.input})
        if tool.destructive and confirm and not confirm(tool, block.input):
            return _tool_result(
                block.id,
                "The user rejected this action. Do NOT retry it — pick a different "
                "approach (e.g. a read-only tool) or finish and tell the user.",
                True)
        try:
            result = tool.execute(block.input, ctx)
        except Exception as e:  # a broken tool never takes down the loop
            logger.exception("[AgentLoop] tool %s raised an exception", tool.name)
            result = ToolResult(f"exception in the tool: {e}", is_error=True)
        if isinstance(result.content, str) and len(result.content) > MAX_TOOL_RESULT_CHARS:
            marca = f"\n[...result truncated: {len(result.content)} characters in total]"
            result = ToolResult(
                result.content[: MAX_TOOL_RESULT_CHARS - len(marca)] + marca,
                is_error=result.is_error,
            )
        if emit:
            emit({"type": "tool_result", "agent": tool.name, "is_error": result.is_error})
        return _tool_result(block.id, result.content, result.is_error)

    def _call_llm(self, messages, tools, emit):
        """A single streaming call to the model. Emits thinking deltas to the
        timeline (on claude-opus-4-8 thinking is omitted unless display=summarized
        is requested). Text is NOT emitted per delta: the `final` event already
        renders the full response."""
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
