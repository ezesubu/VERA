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

    def discover_classes(self, classes) -> None:
        """Registra una lista de clases Tool ya cargadas (p.ej. las que aporta un
        plugin). Ignora la clase base `Tool` y cualquier cosa que no sea una
        subclase de Tool. Reutiliza el mismo gate de duplicados que `register`."""
        for obj in classes:
            if (
                inspect.isclass(obj)
                and issubclass(obj, Tool)
                and obj is not Tool
            ):
                self.register(obj())
                logger.info("[ToolRegistry] tool de plugin registrada: %s", obj().name)

    def discover(self, package) -> None:
        """Importa todos los módulos de `package` y registra cada subclase de Tool
        definida en ellos (instanciada sin argumentos)."""
        for _, modname, _ in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package.__name__}.{modname}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, Tool)
                    and obj is not Tool
                    and obj.__module__ == module.__name__
                ):
                    self.register(obj())
                    logger.info("[ToolRegistry] tool descubierta: %s", obj().name)
