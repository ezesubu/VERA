"""AgentSession: persistent conversation for VERA's brain.

History survives across commands ("create a cube" → "make it red" works).
Reactive (chat) and proactive (watchers, Phase 3) inject turns into the SAME
history via run() / inject().
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40  # fine-grained context trimming arrives with compaction (Phase 4)


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
        should_stop: Optional[Callable[[], bool]] = None,
        image: Optional[dict] = None,
    ) -> dict:
        """Run a command inside the session (mutates `self.messages`).
        `confirm`: override of the destructive gate for this one call
        (e.g. the round-trip to the socket over the live connection).
        `include_destructive`: False = readonly mode (hides destructive tools).
        `should_stop`: cooperative cancellation callback forwarded to the loop.
        `image`: optional attached image forwarded to the loop so the model
        sees it in this turn."""
        with self._lock:
            self._trim()
            return self.loop.run(
                command, emit=emit, messages=self.messages, confirm=confirm,
                include_destructive=include_destructive, should_stop=should_stop,
                image=image,
            )

    def inject(
        self,
        content: str,
        emit: Optional[Callable[[dict], None]] = None,
        confirm: Optional[Callable] = None,
    ) -> dict:
        """Proactive turn (LogWatcher/FPSWatcher in Phase 3): same loop, different source."""
        return self.run(content, emit=emit, confirm=confirm)

    def _trim(self) -> None:
        """Keeps the history bounded. After pruning, the history must ALWAYS
        start on a plain-text user turn: cutting in the middle of a
        tool_use/tool_result pair is a 400 from the API."""
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
                "[AgentSession] _trim emptied the history: no plain-text user turn remained")
