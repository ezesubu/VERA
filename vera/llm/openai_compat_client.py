"""Adapter that duck-types `anthropic.Anthropic` over an OpenAI-compatible backend.

OpenAI, LM Studio (local) and Gemini (OpenAI-compatible endpoint) all speak the
same `chat.completions` format. This client exposes the SAME surface the
`AgentLoop` already uses from Anthropic — `.messages.stream(model, max_tokens,
thinking, system, tools, messages)` as a context manager with
`.get_final_message()` → an object with `.stop_reason` and `.content` (blocks) —
translating in both directions.

The canonical history is kept in Anthropic form; it is translated on the fly to
OpenAI format on every call. That is why you can switch providers mid-session
without losing the history.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List, Optional


# --------- response blocks (re-introspectable: the loop feeds them back in) ---------

class TextBlock(SimpleNamespace):
    def __init__(self, text: str) -> None:
        super().__init__(type="text", text=text)


class ToolUseBlock(SimpleNamespace):
    def __init__(self, id: str, name: str, input: dict) -> None:
        super().__init__(type="tool_use", id=id, name=name, input=input)


class _Message(SimpleNamespace):
    """Normalized final message: mimics anthropic.types.Message."""

    def __init__(self, stop_reason: str, content: list) -> None:
        super().__init__(stop_reason=stop_reason, content=content)


# --------------------------- OUTBOUND translation ---------------------------

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
    """Reads `key` from a block that may be a dict or an object with attributes."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _stringify_content(content: Any) -> str:
    """tool_result.content may be a str or a list of blocks (text/image)."""
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
    """List of Anthropic blocks → OpenAI assistant message (text + tool_calls)."""
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


def _translate_user_multimodal(content_blocks: list) -> dict:
    """List of Anthropic user blocks (text + image) → multimodal OpenAI user
    message. The base64 image is inlined as a data URL."""
    parts: List[dict] = []
    for block in content_blocks:
        btype = _block_attr(block, "type")
        if btype == "text":
            parts.append({"type": "text", "text": _block_attr(block, "text", "")})
        elif btype == "image":
            source = _block_attr(block, "source", {}) or {}
            media_type = _block_attr(source, "media_type", "image/png")
            data = _block_attr(source, "data", "")
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{data}"},
            })
    return {"role": "user", "content": parts}


def _translate_tool_results(content_blocks: list) -> List[dict]:
    """List of Anthropic tool_result → one role:tool message per result."""
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
                # A user-list turn is either tool_results (→ role:tool) or a
                # multimodal turn (text + attached image → multimodal user).
                if any(_block_attr(b, "type") in ("text", "image") for b in content):
                    out.append(_translate_user_multimodal(content))
                else:
                    out.extend(_translate_tool_results(content))
        elif role == "assistant":
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
            else:
                out.append(_translate_assistant(content))
        elif role == "system":
            out.append({"role": "system", "content": content})
    return out


# --------------------------- INBOUND translation ---------------------------

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
    if not blocks:  # empty turn: never return content:[] to the loop
        blocks.append(TextBlock(""))
    return _Message("end_turn", blocks)


# ------------------------------- the client -------------------------------

class _StreamCtx:
    """Iterable context manager that mimics the `messages.stream` surface.

    It calls the backend EAGERLY in __enter__ (no live thinking events are
    emitted for these providers; the loop renders the final text).
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
        return iter(())  # no event streaming in v1

    def get_final_message(self) -> _Message:
        return self._final


class _Messages:
    def __init__(self, owner: "OpenAICompatClient") -> None:
        self._owner = owner

    def stream(self, *, model=None, max_tokens=None, thinking=None,
               system=None, tools=None, messages=None, **_ignored) -> _StreamCtx:
        # `thinking` is accepted and ignored on purpose.
        kwargs: dict = {
            "model": model or self._owner.model,
            "messages": _translate_messages(system, messages or []),
            "tool_choice": "auto",
        }
        translated_tools = _translate_tools(tools)
        if translated_tools:
            kwargs["tools"] = translated_tools
        else:
            # some OpenAI backends reject tool_choice without tools
            kwargs.pop("tool_choice", None)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return _StreamCtx(self._owner._client.chat.completions.create, kwargs)


class OpenAICompatClient:
    """Client shaped like `anthropic.Anthropic` over an OpenAI backend.

    `client` is injectable for tests; in production an `openai.OpenAI` is created
    with `base_url`/`api_key`.
    """

    def __init__(self, base_url: str, api_key: Optional[str], model: str,
                 *, client: Any = None, timeout: Optional[float] = None) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        if client is None:
            import openai  # lazy: only needed in production
            kwargs: dict = {"base_url": base_url, "api_key": api_key or "not-needed"}
            if timeout is not None:  # generous for cold local-model loads
                kwargs["timeout"] = timeout
            client = openai.OpenAI(**kwargs)
        self._client = client
        self.messages = _Messages(self)
