"""
VERA Core Agent — Main orchestrator.

This is the brain of VERA. It receives a natural language command,
plans the steps, and delegates to the appropriate layer:
  1. UE Python API (zero tokens, direct)
  2. Coord Registry Cache (zero tokens, fast)
  3. Local OCR / CV (zero tokens, local)
  4. Gemini Vision (tokens, fallback only)
"""

from __future__ import annotations

import logging
from typing import Optional

from vera.core.planner import Planner
from vera.core.state_machine import UEStateMachine
from vera.cache.coord_registry import CoordRegistry
from vera.cache.action_cache import ActionCache
from vera.perception.screenshot import ScreenshotCapture
from vera.perception.ocr import LocalOCR
from vera.perception.vision import GeminiVision
from vera.actions.mouse import MouseController
from vera.actions.keyboard import KeyboardController
from vera.actions.ue_python import UEPythonBridge

logger = logging.getLogger(__name__)


class VERAAgent:
    """
    Main VERA agent. Orchestrates all sub-systems to fulfill
    a natural language command within the Unreal Engine editor.

    Token Efficiency Strategy:
    --------------------------
    Layer 0: UE Python API      → Direct scripting, 0 tokens
    Layer 1: Coord Registry     → Cached positions, 0 tokens
    Layer 2: Local OCR          → On-device text detection, 0 tokens
    Layer 3: Gemini Vision      → Cloud Vision, tokens (last resort)
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.planner = Planner(config=self.config.get("llm", {}))
        self.state_machine = UEStateMachine()
        self.coord_registry = CoordRegistry()
        self.action_cache = ActionCache()
        self.screenshot = ScreenshotCapture()
        self.ocr = LocalOCR()
        self.vision = GeminiVision(config=self.config.get("llm", {}))
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.ue_bridge = UEPythonBridge()

        logger.info("VERA agent initialized.")

    def run(self, command: str) -> dict:
        """
        Execute a natural language command inside Unreal Engine.

        Args:
            command: Natural language instruction, e.g.
                     "Set default map to Lobby and launch on Android"

        Returns:
            Result dict with status, steps taken, and token usage.
        """
        logger.info(f"Received command: '{command}'")
        result = {"command": command, "steps": [], "tokens_used": 0, "success": False}

        # ── Step 1: Check the semantic action cache ─────────────────────────
        cached = self.action_cache.find_similar(command)
        if cached:
            logger.info("Cache hit — replaying cached action recipe.")
            return self._replay_recipe(cached, result)

        # ── Step 2: Plan the task (uses LLM for planning only) ──────────────
        plan = self.planner.plan(command)
        result["tokens_used"] += plan.tokens_used
        result["steps"] = plan.steps

        # ── Step 3: Execute each step in the plan ───────────────────────────
        for step in plan.steps:
            step_result = self._execute_step(step)
            if not step_result["success"]:
                result["error"] = step_result.get("error", "Unknown error")
                logger.error(f"Step failed: {step} → {result['error']}")
                return result

        # ── Step 4: Save to action cache for future zero-token reuse ────────
        self.action_cache.save(command, plan.steps)

        result["success"] = True
        logger.info(f"Command completed. Tokens used: {result['tokens_used']}")
        return result

    def _execute_step(self, step: dict) -> dict:
        """
        Execute a single planned step using the cheapest available method.
        """
        action_type = step.get("type")
        params = step.get("params", {})

        # Tier 0: Direct UE Python API call (free)
        if action_type == "ue_python":
            return self.ue_bridge.execute(params["script"])

        # Tier 0: Known UI coordinate from registry (free)
        if action_type == "click_element":
            coords = self.coord_registry.get(params["element_id"])
            if coords:
                self.mouse.click(coords["x"], coords["y"])
                return {"success": True}

        # Tier 1: Local OCR to find element (free)
        if action_type == "find_and_click":
            screen = self.screenshot.capture(region=params.get("region"))
            coords = self.ocr.find_text(screen, params["label"])
            if coords:
                # Cache this for next time
                self.coord_registry.save(params["label"], coords)
                self.mouse.click(coords["x"], coords["y"])
                return {"success": True}

        # Tier 2: Gemini Vision fallback (costs tokens)
        if action_type in ("find_and_click", "click_element"):
            logger.warning(f"Falling back to Gemini Vision for: {params}")
            screen = self.screenshot.capture(region=params.get("region"))
            coords, tokens = self.vision.find_element(screen, params.get("label", ""))
            if coords:
                self.coord_registry.save(params.get("element_id", params.get("label")), coords)
                self.mouse.click(coords["x"], coords["y"])
                return {"success": True, "tokens": tokens}

        # Type input
        if action_type == "type_text":
            self.keyboard.type(params["text"])
            return {"success": True}

        # Wait for UI state
        if action_type == "wait_for_state":
            success = self.state_machine.wait_for(params["state"], timeout=params.get("timeout", 30))
            return {"success": success}

        return {"success": False, "error": f"Unknown action type: {action_type}"}

    def _replay_recipe(self, recipe: dict, result: dict) -> dict:
        """Replay a cached action recipe with zero LLM calls."""
        for step in recipe["steps"]:
            step_result = self._execute_step(step)
            if not step_result["success"]:
                result["error"] = step_result.get("error")
                return result
        result["success"] = True
        result["from_cache"] = True
        return result
