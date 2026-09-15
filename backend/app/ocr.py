from __future__ import annotations

import io
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Configurable OCR handler: Callable[[bytes], str]
_OCR_HANDLER: Callable[[bytes], str] | None = None


def set_ocr_handler(handler: Callable[[bytes], str] | None) -> None:
    """Set or override the active OCR handler (useful for testing or custom engines)."""
    global _OCR_HANDLER
    _OCR_HANDLER = handler


def ocr_image_bytes(image_bytes: bytes) -> str:
    """Extract text from raw image bytes using available OCR engines."""
    if _OCR_HANDLER is not None:
        try:
            return _OCR_HANDLER(image_bytes)
        except Exception as exc:
            logger.debug("Custom OCR handler failed: %s", exc)

    # 1. Try pytesseract if available
    try:
        import pytesseract
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(image)
        if text and text.strip():
            return text.strip()
    except (ImportError, Exception) as exc:
        logger.debug("pytesseract OCR not available: %s", exc)

    # 2. Try rapidocr if available
    try:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        result, _ = engine(image_bytes)
        if result:
            lines = [line[1] for line in result if len(line) > 1 and line[1]]
            if lines:
                return "\n".join(lines).strip()
    except (ImportError, Exception) as exc:
        logger.debug("rapidocr OCR not available: %s", exc)

    return ""


def extract_page_ocr_text(page: Any) -> str:
    """Extract and combine text from all embedded images in a PDF page."""
    images = getattr(page, "images", None)
    if not images:
        return ""

    extracted_parts: list[str] = []
    for image_file in images:
        data = getattr(image_file, "data", None)
        if not data:
            continue
        text = ocr_image_bytes(data)
        if text:
            extracted_parts.append(text)

    return "\n\n".join(extracted_parts).strip()
