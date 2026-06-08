"""
Image Text Extractor Service

Extracts text from uploaded images so they can be mapped to domains and
correlated like any other intake source. Text extraction is the priority.

Integration strategy (graceful degradation):
1. If ``settings.VISION_MODEL_ENABLED`` and a vision provider is configured,
   call the vision model (Gemini multimodal or a Gemma multimodal endpoint).
2. Otherwise return an empty extraction with a clear note, so the rest of the
   pipeline keeps working without the model present.

The output is consumed by ``image_domain_mapper`` and ``image_scenario_builder``.
"""

from typing import Dict, List, Any, Optional
import os

import structlog

from app.core.config import settings
from app.services.shared_key_detector import (
    extract_keys_from_text,
    extract_keys_from_filename,
)

logger = structlog.get_logger()


_VISION_PROMPT = (
    "You are an OCR and document-understanding engine for an industrial "
    "operations platform. Extract ALL readable text from this image verbatim. "
    "Include labels, gauge readings, table cells, signage, asset IDs, dates, "
    "and any identifiers. Return plain text only, preserving line breaks."
)


def estimate_processing_seconds(image_bytes: int) -> float:
    """Estimate ingestion+analysis time for a single image (~2-5s via vision)."""
    base = 2.0
    # Larger images cost more.
    return round(base + min(image_bytes / (1024 * 1024), 8) * 0.5, 1)


def requires_confirmation(image_bytes: int) -> bool:
    return image_bytes > settings.VISION_MAX_IMAGE_BYTES


def _extract_with_gemini(content: bytes, mime_type: str) -> Optional[str]:
    """Use google-generativeai multimodal model for text extraction."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("vision_no_api_key")
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(settings.VISION_MODEL_NAME)
        response = model.generate_content([
            _VISION_PROMPT,
            {"mime_type": mime_type, "data": content},
        ])
        return (getattr(response, "text", None) or "").strip()
    except Exception as e:
        logger.error("gemini_vision_failed", error=str(e))
        return None


def _mime_for(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
    }.get(ext, "image/png")


def _image_metadata(content: bytes) -> Dict[str, Any]:
    """Best-effort EXIF/dimension extraction via Pillow."""
    meta: Dict[str, Any] = {"size_bytes": len(content)}
    try:
        from PIL import Image
        import io as _io
        with Image.open(_io.BytesIO(content)) as img:
            meta["width"], meta["height"] = img.size
            meta["format"] = img.format
            exif = getattr(img, "_getexif", lambda: None)()
            if exif:
                meta["has_exif"] = True
    except Exception:
        pass
    return meta


def extract_text_from_image(content: bytes, filename: str) -> Dict[str, Any]:
    """
    Extract text and metadata from an image.

    Returns:
        {
          "type": "image",
          "extracted_text": str,
          "confidence": float,
          "metadata": {...},
          "shared_keys": [...],
          "estimated_seconds": float,
          "requires_confirmation": bool,
          "extraction_method": str,
        }
    """
    metadata = _image_metadata(content)
    extracted_text = ""
    method = "none"
    confidence = 0.0

    if settings.VISION_MODEL_ENABLED:
        mime = _mime_for(filename)
        if settings.VISION_MODEL_PROVIDER == "gemini":
            text = _extract_with_gemini(content, mime)
            if text:
                extracted_text = text
                method = f"gemini:{settings.VISION_MODEL_NAME}"
                confidence = 0.8
        # "gemma" multimodal endpoint integration point: when a multimodal
        # Gemma deployment is available, wire it here. Falls through to note.

    if not extracted_text:
        logger.info("image_text_extraction_unavailable", filename=filename)
        note = (
            "Vision extraction unavailable (VISION_MODEL_ENABLED is off or no "
            "API key). Enable a vision provider to extract text from images."
        )
        return {
            "type": "image",
            "extracted_text": "",
            "confidence": 0.0,
            "metadata": metadata,
            "shared_keys": extract_keys_from_filename(filename),
            "estimated_seconds": estimate_processing_seconds(len(content)),
            "requires_confirmation": requires_confirmation(len(content)),
            "extraction_method": "none",
            "note": note,
        }

    shared_keys = extract_keys_from_filename(filename) + extract_keys_from_text(extracted_text)
    shared_keys = list(dict.fromkeys([k for k in shared_keys if k]))

    return {
        "type": "image",
        "extracted_text": extracted_text,
        "confidence": confidence,
        "metadata": metadata,
        "shared_keys": shared_keys,
        "estimated_seconds": estimate_processing_seconds(len(content)),
        "requires_confirmation": requires_confirmation(len(content)),
        "extraction_method": method,
    }
