"""
VERA State Machine — Tracks and queries the current state of the UE5 editor UI.

Avoids expensive screenshot+LLM calls by using deterministic checks:
window titles, process states, and local OCR on small screen regions.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

import pyautogui
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


class UEEditorState(str, Enum):
    UNKNOWN = "unknown"
    MAIN_EDITOR = "main_editor"
    PROJECT_SETTINGS_OPEN = "project_settings_open"
    MAPS_AND_MODES_ACTIVE = "maps_and_modes_active"
    ANDROID_SETTINGS_ACTIVE = "android_settings_active"
    PACKAGING_SETTINGS_ACTIVE = "packaging_settings_active"
    BUILD_IN_PROGRESS = "build_in_progress"
    BUILD_COMPLETE = "build_complete"
    MATERIAL_EDITOR_OPEN = "material_editor_open"
    BLUEPRINT_EDITOR_OPEN = "blueprint_editor_open"


# Map of states to detectable text signatures (via local OCR, 0 tokens)
STATE_SIGNATURES: dict[UEEditorState, list[str]] = {
    UEEditorState.PROJECT_SETTINGS_OPEN: ["Project Settings", "Maps & Modes"],
    UEEditorState.MAPS_AND_MODES_ACTIVE: ["Game Default Map", "Editor Startup Map"],
    UEEditorState.ANDROID_SETTINGS_ACTIVE: ["Android", "Package Name", "SDK API Level"],
    UEEditorState.BUILD_IN_PROGRESS: ["Cooking", "Packaging", "Compiling Shaders"],
    UEEditorState.BUILD_COMPLETE: ["BUILD SUCCEEDED", "BUILD FAILED", "Deployment complete"],
    UEEditorState.MATERIAL_EDITOR_OPEN: ["Material Editor", "Base Color", "Roughness"],
}


class UEStateMachine:
    """
    Detects the current UE editor state using local OCR.
    Zero LLM tokens — all detection is done on-device.
    """

    def __init__(self):
        self._current_state = UEEditorState.UNKNOWN

    def detect_current_state(self) -> UEEditorState:
        """
        Take a screenshot and detect the current editor state via OCR.
        Returns the detected state without using any LLM tokens.
        """
        # Capture a small region of the screen (top bar + sidebar)
        # to minimize processing time
        screenshot = pyautogui.screenshot()
        # Resize to speed up OCR
        small = screenshot.resize((1280, 720), Image.LANCZOS)
        text = pytesseract.image_to_string(small, config="--psm 11")

        for state, signatures in STATE_SIGNATURES.items():
            if any(sig.lower() in text.lower() for sig in signatures):
                self._current_state = state
                logger.debug(f"Detected state: {state}")
                return state

        self._current_state = UEEditorState.UNKNOWN
        return UEEditorState.UNKNOWN

    def wait_for(self, state: str, timeout: int = 30) -> bool:
        """
        Poll until the editor reaches the desired state or timeout.
        Uses only local OCR — zero LLM tokens.
        """
        target = UEEditorState(state)
        deadline = time.time() + timeout

        while time.time() < deadline:
            current = self.detect_current_state()
            if current == target:
                logger.info(f"State reached: {target}")
                return True
            time.sleep(1.5)

        logger.warning(f"Timeout waiting for state: {target}")
        return False

    @property
    def current_state(self) -> UEEditorState:
        return self._current_state
