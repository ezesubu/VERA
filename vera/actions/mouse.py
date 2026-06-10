"""
VERA Mouse Controller — Precise mouse control with safety guards.
"""

from __future__ import annotations

import logging
import time

import pyautogui

pyautogui.FAILSAFE = True   # Move mouse to top-left corner to abort
pyautogui.PAUSE = 0.05      # Small delay between actions for stability

logger = logging.getLogger(__name__)


class MouseController:
    """Controls mouse movement and clicking within the UE editor."""

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        """Move to (x, y) and click."""
        logger.debug(f"Click ({x}, {y}) button={button} x{clicks}")
        pyautogui.moveTo(x, y, duration=0.15)
        pyautogui.click(x, y, button=button, clicks=clicks, interval=0.1)

    def double_click(self, x: int, y: int) -> None:
        self.click(x, y, clicks=2)

    def right_click(self, x: int, y: int) -> None:
        self.click(x, y, button="right")

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> None:
        """Drag from (x1,y1) to (x2,y2)."""
        pyautogui.moveTo(x1, y1, duration=0.15)
        pyautogui.dragTo(x2, y2, duration=duration, button="left")

    def scroll(self, x: int, y: int, amount: int) -> None:
        """Scroll at position. Positive = up, negative = down."""
        pyautogui.moveTo(x, y, duration=0.1)
        pyautogui.scroll(amount)
