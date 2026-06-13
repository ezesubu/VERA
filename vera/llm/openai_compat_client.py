"""Adaptador que duck-typea `anthropic.Anthropic` sobre un backend OpenAI-compatible.

OpenAI, LM Studio (local) y Gemini (endpoint OpenAI-compatible) hablan el mismo
formato `chat.completions`. Este cliente expone la MISMA superficie que el
`AgentLoop` ya usa de Anthropic — `.messages.stream(model, max_tokens, thinking,
system, tools, messages)` como context manager con `.get_final_message()` →
objeto con `.stop_reason` y `.content` (bloques) — traduciendo en ambos sentidos.

El historial canónico se mantiene en forma Anthropic; se traduce al vuelo a
formato OpenAI en cada llamada. Por eso se puede cambiar de proveedor a mitad de
sesión sin perder el historial.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List, Optional


# --------- bloques de respuesta (re-introspectables: el loop los re-mete) ---------

class TextBlock(SimpleNamespace):
    def __init__(self, text: str) -> None:
        super().__init__(type="text", text=text)


class ToolUseBlock(SimpleNamespace):
    def __init__(self, id: str, name: str, input: dict) -> None:
        super().__init__(type="tool_use", id=id, name=name, input=input)


class _Message(SimpleNamespace):
    """Mensaje final normalizado: imita anthropic.types.Message."""

    def __init__(self, stop_reason: str, content: list) -> None:
        super().__init__(stop_reason=stop_reason, content=content)


# --------------------------- traducción SALIDA ---------------------------

def _translate_tools(tools: Optional[List[dict]]) -> Optional[List[dict]]:
    """Anthropic {name,description,input_schema} → OpenAI function schema."""
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object"}),
            },
        }
        for t in tools
    ]


def _block_attr(block: Any, key: str, default=None):
    """Lee `key` de un bloque que puede ser dict o un objeto con atributos."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _stringify_content(content: Any) -> str:
    """tool_result.content puede ser str o lista de bloques (texto/imagen)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if _block_attr(b, "type") == "text":
                parts.append(_block_attr(b, "text", ""))
            else:
                parts.append(json.dumps(b) if isinstance(b, dict) else str(b))
        return "\n".join(parts)
    return str(content)


def _translate_assistant(content_blocks: list) -> dict:
    """Lista de bloques Anthropic → mensaje assistant OpenAI (texto + tool_calls)."""
    text_parts: List[str] = []
    tool_calls: List[dict] = []
    for block in content_blocks:
        btype = _block_attr(block, "type")
        if btype == "text":
            text_parts.append(_block_attr(block, "text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": _block_attr(block, "id"),
                "type": "function",
                "function": {
                    "name": _block_attr(block, "name"),
                    "arguments": json.dumps(_block_attr(block, "input", {}) or {}),
                },
            })
    msg: dict = {"role": "assistant", "content": "\n".join(text_parts)}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _translate_tool_results(content_blocks: list) -> List[dict]:
    """Lista de tool_result Anthropic → un mensaje role:tool por cada uno."""
    out = []
    for block in content_blocks:
        if _block_attr(block, "type") == "tool_result":
            out.append({
                "role": "tool",
                "tool_call_id": _block_attr(block, "tool_use_id"),
                "content": _stringify_content(_block_attr(block, "content", "")),
            })
    return out


def _translate_messages(system: Optional[str], messages: List[dict]) -> List[dict]:
    out: List[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # user-con-tool_results → mensajes role:tool
                out.extend(_translate_tool_results(content))
        elif role == "assistant":
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
            else:
                out.append(_translate_assistant(content))
        elif role == "system":
            out.append({"role": "system", "content": content})
    return out


# --------------------------- traducción ENTRADA ---------------------------

def _translate_response(completion: Any) -> _Message:
    message = completion.choices[0].message
    tool_calls = getattr(message, "tool_calls", None)
    blocks: list = []
    text = getattr(message, "content", None)
    if text:
        blocks.append(TextBlock(text))
    if tool_calls:
        for tc in tool_calls:
            args = tc.function.arguments or ""
            try:
                parsed = json.loads(args) if args.strip() else {}
            except (ValueError, AttributeError):
                parsed = {}
            blocks.append(ToolUseBlock(id=tc.id, name=tc.function.name, input=parsed))
        return _Message("tool_use", blocks)
    if not blocks:  # turno vacío: nunca devolver content:[] al loop
        blocks.append(TextBlock(""))
    return _Message("end_turn", blocks)


# ------------------------------- el cliente -------------------------------

class _StreamCtx:
    """Context manager iterable que imita la superficie de `messages.stream`.

    Hace la llamada al backend de forma EAGER en __enter__ (no se emiten eventos
    de thinking en vivo para estos proveedores; el loop pinta el texto final).
    """

    def __init__(self, create_fn, kwargs) -> None:
        self._create_fn = create_fn
        self._kwargs = kwargs
        self._final: Optional[_Message] = None

    def __enter__(self) -> "_StreamCtx":
        completion = self._create_fn(**self._kwargs)
        self._final = _translate_response(completion)
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def __iter__(self):
        return iter(())  # sin streaming de eventos en v1

    def get_final_message(self) -> _Message:
        return self._final


class _Messages:
    def __init__(self, owner: "OpenAICompatClient") -> None:
        self._owner = owner

    def stream(self, *, model=None, max_tokens=None, thinking=None,
               system=None, tools=None, messages=None, **_ignored) -> _StreamCtx:
        # `thinking` se acepta y se ignora a propósito.
        kwargs: dict = {
            "model": model or self._owner.model,
            "messages": _translate_messages(system, messages or []),
            "tool_choice": "auto",
        }
        translated_tools = _translate_tools(tools)
        if translated_tools:
            kwargs["tools"] = translated_tools
        else:
            # algunos backends OpenAI rechazan tool_choice sin tools
            kwargs.pop("tool_choice", None)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return _StreamCtx(self._owner._client.chat.completions.create, kwargs)


class OpenAICompatClient:
    """Cliente con forma de `anthropic.Anthropic` sobre un backend OpenAI.

    `client` es inyectable para tests; en producción se crea un `openai.OpenAI`
    con `base_url`/`api_key`.
    """

    def __init__(self, base_url: str, api_key: Optional[str], model: str,
                 *, client: Any = None) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        if client is None:
            import openai  # lazy: solo necesario en producción
            client = openai.OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        self._client = client
        self.messages = _Messages(self)
