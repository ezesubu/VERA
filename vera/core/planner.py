"""
VERA Planner — Converts natural language into an executable step plan.

Uses the LLM sparingly: only to decompose the high-level command
into discrete typed steps. Each step is then executed locally.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """
You are VERA, an AI agent that controls the Unreal Engine 5 editor.
Your job is to convert a user command into a JSON array of discrete steps.

Available step types:
- ue_python: Run a UE Python script directly in the editor
- click_element: Click a known UI element by its registry ID
- find_and_click: Find text on screen and click it (uses OCR)
- type_text: Type text into the currently focused field
- wait_for_state: Wait until the UI reaches a specific state
- key_combo: Press a keyboard shortcut

RULES:
1. Prefer "ue_python" steps over visual steps — they are instant and free.
2. Only use "find_and_click" for things that cannot be scripted via Python.
3. Be specific with element IDs and labels.
4. Return ONLY a valid JSON object, no markdown, no explanation.

OUTPUT FORMAT:
{
  "steps": [
    {"type": "ue_python", "params": {"script": "import unreal; ..."}},
    {"type": "find_and_click", "params": {"label": "Maps & Modes", "region": "sidebar"}},
    {"type": "type_text", "params": {"text": "/Game/Lobby/Lobby"}},
    {"type": "key_combo", "params": {"keys": ["ctrl", "s"]}}
  ],
  "description": "Brief explanation of the plan"
}
"""


@dataclass
class Plan:
    steps: list[dict] = field(default_factory=list)
    description: str = ""
    tokens_used: int = 0


class Planner:
    """
    Converts natural language commands into executable step plans.
    Uses Gemini text (NOT vision) for maximum token efficiency.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        api_key = self.config.get("api_key") or __import__("os").getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
        # Use Flash for planning — cheapest model
        self.model = genai.GenerativeModel(
            model_name=self.config.get("model", "gemini-2.0-flash"),
            system_instruction=PLANNER_SYSTEM_PROMPT,
        )

    def plan(self, command: str) -> Plan:
        """
        Convert a natural language command into a Plan.

        Args:
            command: e.g. "Set default map to Lobby and launch on Android"

        Returns:
            Plan object with steps and token count.
        """
        logger.info(f"Planning command: '{command}'")

        try:
            response = self.model.generate_content(
                command,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    max_output_tokens=1024,  # Plans are short — cap tokens
                    temperature=0.0,          # Deterministic planning
                ),
            )

            raw = response.text.strip()
            data = json.loads(raw)
            tokens = response.usage_metadata.total_token_count if response.usage_metadata else 0

            logger.info(f"Plan created with {len(data['steps'])} steps. Tokens: {tokens}")
            return Plan(
                steps=data.get("steps", []),
                description=data.get("description", ""),
                tokens_used=tokens,
            )

        except Exception as e:
            logger.error(f"Planning failed: {e}")
            return Plan(steps=[], tokens_used=0)
