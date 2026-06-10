"""
VERA Local OCR — On-device text detection using Tesseract.
Zero LLM tokens. Used before falling back to Gemini Vision.
"""

from __future__ import annotations

import logging
from typing import Optional

import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


class LocalOCR:
    """
    Finds text in screenshots using Tesseract OCR.
    Completely free — runs locally, zero API calls.
    """

    def find_text(
        self,
        image: Image.Image,
        label: str,
        confidence_threshold: float = 60.0,
    ) -> Optional[dict]:
        """
        Find text in an image and return its center coordinates.

        Args:
            image: PIL Image to search in
            label: Text string to find
            confidence_threshold: Minimum OCR confidence (0-100)

        Returns:
            {"x": int, "y": int} or None if not found
        """
        try:
            data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                config="--psm 11",
            )

            label_lower = label.lower()
            n = len(data["text"])

            for i in range(n):
                word = data["text"][i].strip().lower()
                conf = float(data["conf"][i])

                if label_lower in word and conf >= confidence_threshold:
                    x = data["left"][i] + data["width"][i] // 2
                    y = data["top"][i] + data["height"][i] // 2
                    logger.info(f"OCR found '{label}' at ({x}, {y}) conf={conf:.1f}")
                    return {"x": x, "y": y, "confidence": conf / 100.0}

            # Multi-word search: try sliding window over words
            words = [data["text"][i].strip() for i in range(n)]
            full_text = " ".join(words).lower()
            if label_lower in full_text:
                # Find approximate position of the phrase
                idx = full_text.find(label_lower)
                word_idx = len(full_text[:idx].split())
                if word_idx < n:
                    x = data["left"][word_idx] + data["width"][word_idx] // 2
                    y = data["top"][word_idx] + data["height"][word_idx] // 2
                    logger.info(f"OCR found phrase '{label}' at ({x}, {y})")
                    return {"x": x, "y": y, "confidence": 0.7}

        except Exception as e:
            logger.warning(f"OCR error for '{label}': {e}")

        return None

    def extract_all_text(self, image: Image.Image) -> str:
        """Extract all visible text from an image."""
        try:
            return pytesseract.image_to_string(image, config="--psm 11")
        except Exception as e:
            logger.warning(f"OCR extraction failed: {e}")
            return ""
