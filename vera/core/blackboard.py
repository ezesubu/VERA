"""
VERA Blackboard — Shared Memory Pool for the Agent Crew.

The Blackboard acts as the central hub of context. It connects the 
CoordRegistry, ActionCache, and holds real-time Editor Context 
so all sub-agents (Manager, Perception, QA, UE Python) share the same state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class Blackboard:
    """Shared editor state + the progress channel toward the UI.

    The AgentLoop uses this only for `progress_callback` / `report_progress`. The
    legacy zero-token caches (CoordRegistry / SemanticMemory) were removed along
    with the old agent crew."""

    def __init__(self):
        self.task_queue = []

        # Ephemeral Memory (Current Unreal Editor State)
        self._context: Dict[str, Any] = {}
        self._context_timestamps: Dict[str, float] = {}

        # Progress channel toward the UI (vera_server wires it up per connection)
        self.progress_callback = None

    def report_progress(self, agent: str, msg: str) -> None:
        """Emits a progress event toward the UI. With no callback connected it's a
        no-op; a broken callback never interrupts the agents."""
        self._emit({"type": "progress", "agent": agent, "msg": msg})

    def report_image(self, path: str) -> None:
        """Emits an image (viewport capture) toward the UI."""
        self._emit({"type": "image", "path": path})

    def _emit(self, event: dict) -> None:
        cb = self.progress_callback
        if cb is None:
            return
        try:
            cb(event)
        except Exception:
            logger.warning("[Blackboard] progress_callback failed; ignored", exc_info=True)

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
