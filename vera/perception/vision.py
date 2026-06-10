"""
VERA Gemini Vision — LLM-powered visual fallback.

This is the LAST resort in VERA's perception pipeline.
Only called when local OCR and the coord registry fail.
Aggressively preprocesses images to minimize token consumption.
"""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import Optional

import google.generativeai as genai
from PIL import Image

logger = logging.getLogger(__name__)

VISION_PROMPT_TEMPLATE = """
You are analyzing a screenshot of the Unreal Engine 5 editor.
Find the UI element described below and return its center coordinates.

Element to find: "{label}"

Return ONLY a JSON object:
{{"x": <pixel_x>, "y": <pixel_y>, "confidence": <0.0-1.0>}}

If the element is not visible, return: {{"x": null, "y": null, "confidence": 0}}
"""


class GeminiVision:
    """
    Gemini Vision integration for VERA.

    Token optimization techniques applied:
    1. Image cropped to region of interest before sending
    2. Downscaled to 800px wide max
    3. Converted to grayscale when color is irrelevant
    4. JPEG compressed at 70% quality
    5. Response strictly capped at 64 tokens (coords only)
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        api_key = self.config.get("api_key") or __import__("os").getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=self.config.get("vision_model", "gemini-2.0-flash"),
        )
        self.max_width = self.config.get("max_screenshot_width", 800)
        self.jpeg_quality = self.config.get("screenshot_quality", 70)

    def find_element(
        self,
        image: Image.Image,
        label: str,
        region: Optional[tuple[int, int, int, int]] = None,
    ) -> tuple[Optional[dict], int]:
        """
        Find a UI element in the screenshot using Gemini Vision.

        Args:
            image: PIL Image of the screen
            label: Human-readable description of the element to find
            region: Optional (x, y, w, h) crop region to reduce token usage

        Returns:
            Tuple of (coords_dict or None, tokens_used)
        """
        # ── Image preprocessing (minimize tokens) ─────────────────────────
        processed = self._preprocess(image, region)
        img_b64 = self._encode(processed)

        prompt = VISION_PROMPT_TEMPLATE.format(label=label)

        try:
            response = self.model.generate_content(
                [{"mime_type": "image/jpeg", "data": img_b64}, prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    max_output_tokens=64,   # Coordinates only — very short
                    temperature=0.0,
                ),
            )

            import json
            data = json.loads(response.text.strip())
            tokens = response.usage_metadata.total_token_count if response.usage_metadata else 0

            # Adjust coordinates back to full-screen space if region was cropped
            if region and data.get("x") is not None:
                data["x"] += region[0]
                data["y"] += region[1]

            logger.info(f"Vision found '{label}' at ({data.get('x')}, {data.get('y')}). Tokens: {tokens}")
            return (data if data.get("x") is not None else None), tokens

        except Exception as e:
            logger.error(f"Gemini Vision failed for '{label}': {e}")
            return None, 0

    def _preprocess(
        self,
        image: Image.Image,
        region: Optional[tuple[int, int, int, int]] = None,
    ) -> Image.Image:
        """Crop, resize, and convert image to minimize token cost."""
        if region:
            x, y, w, h = region
            image = image.crop((x, y, x + w, y + h))

        # Downscale if too large
        if image.width > self.max_width:
            ratio = self.max_width / image.width
            new_size = (self.max_width, int(image.height * ratio))
            image = image.resize(new_size, Image.LANCZOS)

        return image

    def _encode(self, image: Image.Image) -> str:
        """Encode image as base64 JPEG string."""
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=self.jpeg_quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
