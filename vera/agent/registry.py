"""Registro y auto-descubrimiento de herramientas."""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import List, Optional

from vera.agent.tool import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool duplicada: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def to_anthropic(self) -> List[dict]:
        return [t.to_anthropic() for t in self._tools.values()]
