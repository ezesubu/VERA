"""AgentSession: conversación persistente del cerebro de VERA.

El historial sobrevive entre comandos ("creá un cubo" → "hacelo rojo" funciona).
Reactivo (chat) y proactivo (watchers, Fase 3) inyectan turnos al MISMO historial
vía run() / inject().
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

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
    ) -> dict:
        with self._lock:
            self._trim()
            return self.loop.run(command, emit=emit, messages=self.messages, confirm=confirm)

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
