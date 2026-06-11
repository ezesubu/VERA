"""
VERA Blackboard — Shared Memory Pool for the Agent Crew.

The Blackboard acts as the central hub of context. It connects the 
CoordRegistry, ActionCache, and holds real-time Editor Context 
so all sub-agents (Manager, Perception, QA, UE Python) share the same state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from vera.core.memory import SemanticMemory
from vera.cache.coord_registry import CoordRegistry

logger = logging.getLogger(__name__)


class Blackboard:
    """
    Shared memory space for VERA agents.
    """

    def __init__(self):
        # Persistent Memory (Zero-token caches)
        self.coord_registry = CoordRegistry()
        self.action_cache = SemanticMemory()
        self.task_queue = []

        # Ephemeral Memory (Current Unreal Editor State)
        self._context: Dict[str, Any] = {}
        self._context_timestamps: Dict[str, float] = {}

        # Canal de progreso hacia la UI (lo conecta vera_server por conexión)
        self.progress_callback = None

    def report_progress(self, agent: str, msg: str) -> None:
        """Emite un evento de progreso hacia la UI. Sin callback conectado es no-op;
        un callback roto jamás interrumpe a los agentes."""
        self._emit({"type": "progress", "agent": agent, "msg": msg})

    def report_image(self, path: str) -> None:
        """Emite una imagen (captura del viewport) hacia la UI."""
        self._emit({"type": "image", "path": path})

    def _emit(self, event: dict) -> None:
        cb = self.progress_callback
        if cb is None:
            return
        try:
            cb(event)
        except Exception:
            logger.warning("[Blackboard] progress_callback falló; se ignora", exc_info=True)

    def enqueue_task(self, task: str):
        self.task_queue.append(task)
        logger.debug(f"[Blackboard] Task enqueued: '{task}'")
        
    def dequeue_task(self) -> str:
        if self.task_queue:
            task = self.task_queue.pop(0)
            logger.debug(f"[Blackboard] Task dequeued: '{task}'")
            return task
        return None

    def set_context(self, key: str, value: Any) -> None:
        """Update the shared editor context with a timestamp."""
        import time
        self._context[key] = value
        self._context_timestamps[key] = time.time()
        logger.debug(f"Blackboard updated: {key} = {value}")

    def get_context(self, key: str, default: Any = None) -> Any:
        """Retrieve a value, processing memory decay first."""
        self._process_memory_decay()
        return self._context.get(key, default)

    def _process_memory_decay(self, max_age_seconds: float = 300.0):
        """Removes ephemeral context that is too old (e.g., 5 minutes)."""
        import time
        current_time = time.time()
        stale_keys = []
        for key, timestamp in self._context_timestamps.items():
            if current_time - timestamp > max_age_seconds:
                stale_keys.append(key)
                
        for key in stale_keys:
            del self._context[key]
            del self._context_timestamps[key]
            logger.debug(f"[Blackboard] Memory Decay: Forgot stale context '{key}'")

    def clear_context(self) -> None:
        """Clear the ephemeral context between completely distinct tasks."""
        self._context.clear()
        self._context_timestamps.clear()
        logger.debug("Blackboard context cleared.")

    def get_summary(self) -> str:
        """Return a string summary of the current non-decayed context."""
        self._process_memory_decay()
        if not self._context:
            return "Editor Context: Unknown / No context set."

        lines = ["Editor Context:"]
        for k, v in self._context.items():
            lines.append(f" - {k}: {v}")
        return "\n".join(lines)
