"""AgentSession: conversación persistente del cerebro de VERA.

El historial sobrevive entre comandos ("creá un cubo" → "hacelo rojo" funciona).
Reactivo (chat) y proactivo (watchers, Fase 3) inyectan turnos al MISMO historial
vía run() / inject().
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40  # el truncado de contexto fino llega con compaction (Fase 4)


class AgentSession:
    def __init__(self, loop) -> None:
        self.loop = loop
        self.messages: list = []
        self._lock = threading.Lock()

    def run(
        self,
        command: str,
        emit: Optional[Callable[[dict], None]] = None,
        confirm: Optional[Callable] = None,
        include_destructive: bool = True,
    ) -> dict:
        """Ejecuta un comando dentro de la sesión (muta `self.messages`).
        `confirm`: override del gate destructivo para esta llamada puntual
        (p.ej. el round-trip al socket de la conexión en curso).
        `include_destructive`: False = modo readonly (esconde tools destructivas)."""
        with self._lock:
            self._trim()
            return self.loop.run(
                command, emit=emit, messages=self.messages, confirm=confirm,
                include_destructive=include_destructive,
            )

    def inject(
        self,
        content: str,
        emit: Optional[Callable[[dict], None]] = None,
        confirm: Optional[Callable] = None,
    ) -> dict:
        """Turno proactivo (LogWatcher/FPSWatcher en Fase 3): mismo loop, otra fuente."""
        return self.run(content, emit=emit, confirm=confirm)

    def _trim(self) -> None:
        """Mantiene el historial acotado. Después de podar, el historial debe
        arrancar SIEMPRE en un turno user de texto plano: cortar en medio de un
        par tool_use/tool_result es un 400 de la API."""
        if len(self.messages) <= MAX_HISTORY_MESSAGES:
            return
        del self.messages[: len(self.messages) - MAX_HISTORY_MESSAGES]
        while self.messages and not (
            self.messages[0].get("role") == "user"
            and isinstance(self.messages[0].get("content"), str)
        ):
            self.messages.pop(0)
        if not self.messages:
            logger.warning(
                "[AgentSession] _trim vació el historial: no quedó ningún turno user de texto plano")
