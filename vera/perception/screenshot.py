"""
VERA Screenshot Capture — Efficient screen capture utilities.
"""

from __future__ import annotations

import logging
from typing import Optional

import pyautogui
from PIL import Image

logger = logging.getLogger(__name__)


class ScreenshotCapture:
    """Captures screenshots with optional region cropping."""

    def capture(
        self,
        region: Optional[str | tuple] = None,
    ) -> Image.Image:
        """
        Capture the screen or a specific region.

        Args:
            region: None (full screen), a tuple (x,y,w,h), or a
                    named region string like "sidebar", "topbar", "viewport"

        Returns:
            PIL Image of the captured region.
        """
        named_regions = {
            "sidebar":   (0, 0, 300, 1080),
            "topbar":    (0, 0, 1920, 60),
            "statusbar": (0, 1020, 1920, 60),
            "viewport":  (300, 60, 1320, 900),
            "details":   (1620, 60, 300, 900),
        }

        if isinstance(region, str):
            region = named_regions.get(region)

        if region:
            x, y, w, h = region
            return pyautogui.screenshot(region=(x, y, w, h))

        return pyautogui.screenshot()
