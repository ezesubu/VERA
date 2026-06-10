"""
VERA Coordinate Registry — Persistent cache of known UI element positions.

After VERA discovers where a button/field lives on screen (via OCR or Vision),
it saves the coordinates here. Future interactions with that element
cost zero tokens — just a dict lookup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path(__file__).parent.parent.parent / "registry" / "ue5_coords.json"


class CoordRegistry:
    """
    JSON-backed coordinate cache for UE5 UI elements.
    All reads/writes are local — zero tokens, zero API calls.
    """

    def __init__(self, registry_path: Optional[Path] = None):
        self.path = registry_path or DEFAULT_REGISTRY_PATH
        self._registry: dict[str, dict] = {}
        self._load()

    def get(self, element_id: str) -> Optional[dict]:
        """
        Get cached coordinates for a UI element.

        Args:
            element_id: Unique identifier for the element, e.g. "maps_and_modes_tab"

        Returns:
            {"x": int, "y": int} or None if not cached
        """
        entry = self._registry.get(element_id)
        if entry:
            logger.debug(f"Coord cache HIT: '{element_id}' → ({entry['x']}, {entry['y']})")
        return entry

    def save(self, element_id: str, coords: dict) -> None:
        """
        Cache coordinates for a UI element.

        Args:
            element_id: Unique identifier
            coords: {"x": int, "y": int} dict
        """
        self._registry[element_id] = {"x": coords["x"], "y": coords["y"]}
        self._persist()
        logger.info(f"Coord cached: '{element_id}' → ({coords['x']}, {coords['y']})")

    def invalidate(self, element_id: str) -> None:
        """Remove a cached coordinate (e.g. after UI layout change)."""
        if element_id in self._registry:
            del self._registry[element_id]
            self._persist()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._registry = json.loads(self.path.read_text(encoding="utf-8"))
                logger.debug(f"Loaded {len(self._registry)} cached coordinates.")
            except Exception as e:
                logger.warning(f"Failed to load coord registry: {e}")
                self._registry = {}
        else:
            self._registry = {}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._registry, indent=2),
            encoding="utf-8",
        )
