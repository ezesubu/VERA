"""
VERA Keyboard Controller — Keyboard input and shortcuts.
"""

from __future__ import annotations

import logging
import time

import pyautogui

logger = logging.getLogger(__name__)


class KeyboardController:
    """Handles keyboard input for the UE editor."""

    def type(self, text: str, interval: float = 0.02) -> None:
        """Type a string of text."""
        logger.debug(f"Typing: '{text}'")
        pyautogui.typewrite(text, interval=interval)

    def hotkey(self, *keys: str) -> None:
        """Press a keyboard shortcut. e.g. hotkey('ctrl', 's')"""
        logger.debug(f"Hotkey: {'+'.join(keys)}")
        pyautogui.hotkey(*keys)

    def press(self, key: str) -> None:
        """Press a single key."""
        pyautogui.press(key)

    def clear_and_type(self, text: str) -> None:
        """Select all text in focused field and replace it."""
        self.hotkey("ctrl", "a")
        time.sleep(0.05)
        self.type(text)
