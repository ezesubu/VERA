"""
VERA Action Cache — Semantic cache for completed workflows.

When VERA successfully completes a command, it stores the full
step recipe here. Future similar commands are matched via local
sentence embeddings (no API call) and replayed for free.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path(__file__).parent.parent.parent / "registry" / "action_cache.json"
SIMILARITY_THRESHOLD = 0.82  # Cosine similarity threshold for a cache hit


class ActionCache:
    """
    Semantic action cache using local sentence embeddings.
    Stores successful workflows and replays them for similar commands.
    Zero tokens for cache hits — all matching done locally.
    """

    def __init__(self, cache_path: Optional[Path] = None):
        self.path = cache_path or DEFAULT_CACHE_PATH
        self._entries: list[dict] = []
        self._embedder = None
        self._load()

    def find_similar(self, command: str) -> Optional[dict]:
        """
        Find a cached recipe semantically similar to the given command.

        Args:
            command: Natural language command to match

        Returns:
            Cached recipe dict or None if no match above threshold
        """
        if not self._entries:
            return None

        embedder = self._get_embedder()
        if embedder is None:
            return None  # Embedder not available — skip cache

        try:
            query_vec = embedder.encode([command], normalize_embeddings=True)[0]
            best_score = 0.0
            best_entry = None

            for entry in self._entries:
                stored_vec = np.array(entry["embedding"])
                score = float(np.dot(query_vec, stored_vec))
                if score > best_score:
                    best_score = score
                    best_entry = entry

            if best_score >= SIMILARITY_THRESHOLD:
                logger.info(f"Action cache HIT (score={best_score:.3f}): '{best_entry['command']}'")
                return best_entry

            logger.debug(f"Action cache MISS (best score={best_score:.3f})")
        except Exception as e:
            logger.warning(f"Action cache lookup failed: {e}")

        return None

    def save(self, command: str, steps: list[dict]) -> None:
        """
        Store a successful command + steps in the cache.

        Args:
            command: The original natural language command
            steps: The list of executed steps
        """
        embedder = self._get_embedder()
        if embedder is None:
            return

        try:
            embedding = embedder.encode([command], normalize_embeddings=True)[0].tolist()
            entry = {"command": command, "steps": steps, "embedding": embedding}
            self._entries.append(entry)
            self._persist()
            logger.info(f"Action cached: '{command}' ({len(steps)} steps)")
        except Exception as e:
            logger.warning(f"Failed to cache action: {e}")

    def _get_embedder(self):
        """Lazy-load the sentence transformer (local model, free)."""
        if self._embedder is not None:
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded local sentence embedder.")
        except ImportError:
            logger.warning("sentence-transformers not installed. Action cache disabled.")
            self._embedder = None
        return self._embedder

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._entries = json.loads(self.path.read_text(encoding="utf-8"))
                logger.debug(f"Loaded {len(self._entries)} cached actions.")
            except Exception:
                self._entries = []

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._entries, indent=2),
            encoding="utf-8",
        )
