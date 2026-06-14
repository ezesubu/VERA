"""Tool contract for VERA's brain."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ToolResult:
    """Result of executing a tool. `content` goes back to the model.

    `content` can be a string (plain text) or a list of API content blocks
    — e.g. text + image for perception tools (see `image_block`).
    """
    content: Any
    is_error: bool = False


def image_block(data_b64: str, media_type: str = "image/png") -> dict:
    """Image content block (base64) to return inside a ToolResult.

    `media_type` accepted by the API: "image/png", "image/jpeg",
    "image/gif", "image/webp". Any other value causes a 400.
    """
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data_b64},
    }


@dataclass
class ToolContext:
    """Services the AgentLoop passes to each tool in execute()."""
    bridge_port: int = 9878
    emit: Optional[Callable[[dict], None]] = None  # event emitter to the UI
    llm: Any = None                                 # LLM client for sub-calls

    def report(self, agent: str, msg: str) -> None:
        """Emit a progress event if a channel is connected (best-effort)."""
        if self.emit:
            self.emit({"type": "progress", "agent": agent, "msg": msg})


class Tool:
    """Base class of every tool. Subclass it and define the attributes.

    A contributor adds a capability by creating a file in
    vera/agent/tools/ with a Tool subclass — the ToolRegistry discovers it.
    """
    name: str = ""
    description: str = ""           # what it does + WHEN to use it (read by the model)
    input_schema: dict = {}         # JSON Schema of the arguments
    destructive: bool = False       # requires confirmation? (irreversible)

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def to_anthropic(self, compact: bool = False) -> dict:
        """Shape expected by the `tools` parameter of the Messages API.

        `compact=True` trims the `description` to its first sentence to shrink
        the per-turn payload for small local-model contexts.
        `name`/`input_schema` stay untouched."""
        from vera.agent.registry import _first_sentence

        description = _first_sentence(self.description) if compact else self.description
        return {
            "name": self.name,
            "description": description,
            "input_schema": self.input_schema,
        }
