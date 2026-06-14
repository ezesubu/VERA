"""Tool registry and auto-discovery."""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import List, Optional

from vera.agent.tool import Tool

logger = logging.getLogger(__name__)

_COMPACT_DESC_FALLBACK = 140  # chars, when there is no sentence break


def _first_sentence(text: str) -> str:
    """First sentence of `text` (up to and including the first ". "). If there
    is no sentence break, fall back to the first ~140 chars on a word boundary."""
    if not text:
        return text
    idx = text.find(". ")
    if idx != -1:
        return text[: idx + 1]  # keep the period, drop the trailing space + rest
    if len(text) <= _COMPACT_DESC_FALLBACK:
        return text
    cut = text[:_COMPACT_DESC_FALLBACK]
    sp = cut.rfind(" ")
    if sp > 0:
        cut = cut[:sp]
    return cut


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def to_anthropic(self, compact: bool = False) -> List[dict]:
        """Anthropic `tools` schemas. When `compact=True`, trim each tool's
        description to its first sentence to shrink the per-turn payload for
        small local-model contexts. `name`/`input_schema` are never touched."""
        return [t.to_anthropic(compact=compact) for t in self._tools.values()]

    def discover_classes(self, classes) -> None:
        """Register a list of already-loaded Tool classes (e.g. the ones a plugin
        contributes). Ignores the base `Tool` class and anything that is not a
        Tool subclass. Reuses the same duplicate gate as `register`."""
        for obj in classes:
            if (
                inspect.isclass(obj)
                and issubclass(obj, Tool)
                and obj is not Tool
            ):
                self.register(obj())
                logger.info("[ToolRegistry] plugin tool registered: %s", obj().name)

    def discover(self, package) -> None:
        """Import every module of `package` and register each Tool subclass
        defined in them (instantiated with no arguments)."""
        for _, modname, _ in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package.__name__}.{modname}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, Tool)
                    and obj is not Tool
                    and obj.__module__ == module.__name__
                ):
                    self.register(obj())
                    logger.info("[ToolRegistry] tool discovered: %s", obj().name)
