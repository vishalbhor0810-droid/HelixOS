"""
Vision-model fallback for pages local OCR can't read well (mainly handwriting).
EasyOCR is trained on printed text; when its confidence on a scanned page is low, the
page image is sent to the configured LLM provider's vision model for transcription.
Calls are synchronous because document extraction runs synchronously during indexing.
"""
import io
import re
import time
import base64
import logging
from typing import Optional

import httpx
from backend.config import settings

logger = logging.getLogger("helix.vision_ocr")

# Default vision-capable model per provider (override with VISION_MODEL in .env)
DEFAULT_VISION_MODELS = {
    "groq": "qwen/qwen3.8-27b",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
}

# Keep the encoded image well under provider request limits (Groq: 4MB base64)
MAX_IMAGE_SIDE = 2000
JPEG_QUALITY = 85
REQUEST_TIMEOUT = 60.0

# Rate limits (HTTP 429): free tiers allow only a couple of page images per minute,
# so wait for the limit to reset and retry instead of losing the page
MAX_RETRIES = 5
DEFAULT_RETRY_WAIT = 30.0
MAX_RETRY_WAIT = 120.0

# Reasoning models (e.g. Qwen) may prefix their reply with a <think> block
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# Groq reset headers look like "32.707s", "7m12s" or "250ms"
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")

TRANSCRIBE_PROMPT = (
    "This is one page of a scanned document. It may be handwritten.\n"
    "1. Transcribe all text on the page as accurately as you can, keeping the original wording. "
    "For words you cannot read, give your best guess.\n"
    "2. If the page names a subject, course or topic, often as an abbreviation such as "
    "'Sub: BCN' or 'C S L', write a line 'Subject: ' with the full subject name followed by "
    "its abbreviation without spaces, e.g. 'Subject: Blockchain (BCN)' or "
    "'Subject: Cyber Security and Laws (CSL)'.\n"
    "3. On the last line write 'Summary: ' followed by one sentence describing the page "
    "(type of document and full subject name, e.g. 'Handwritten assignment on blockchain consensus').\n"
    "Reply with the transcription, subject line and summary only."
)


def _vision_model() -> Optional[str]:
    return settings.VISION_MODEL or DEFAULT_VISION_MODELS.get(settings.LLM_PROVIDER)


def is_available() -> bool:
    key = settings.LLM_API_KEY
    return (
        settings.VISION_FALLBACK
        and bool(key and key != "your_api_key_here")
        and _vision_model() is not None
    )


def _encode_jpeg(pil_image) -> str:
    img = pil_image.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _parse_duration(value: str) -> Optional[float]:
    """Seconds from a retry-after style header: "12", "32.707s", "7m12s", "250ms"."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    units = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    parts = _DURATION_RE.findall(value)
    if not parts:
        return None
    return sum(float(n) * units[u] for n, u in parts)


def _retry_wait(resp: httpx.Response) -> float:
    for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        wait = _parse_duration(resp.headers.get(header, ""))
        if wait is not None:
            return min(max(wait, 1.0) + 1.0, MAX_RETRY_WAIT)
    return DEFAULT_RETRY_WAIT


def _post(url: str, headers: dict, payload: dict) -> httpx.Response:
    """POST, waiting out rate limits (429) and transient server errors (5xx) before retrying."""
    for attempt in range(MAX_RETRIES + 1):
        resp = httpx.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        retryable = resp.status_code == 429 or resp.status_code >= 500
        if not retryable or attempt == MAX_RETRIES:
            resp.raise_for_status()
            return resp
        wait = _retry_wait(resp) if resp.status_code == 429 else DEFAULT_RETRY_WAIT
        logger.info(f"Vision request got HTTP {resp.status_code}, retrying in {wait:.0f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})")
        time.sleep(wait)
    return resp


def _call_openai_compatible(base_url: str, model: str, image_b64: str) -> str:
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": TRANSCRIBE_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        }],
        "temperature": 0.0,
        "max_tokens": 2000,
    }
    headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"}
    resp = _post(f"{base_url.rstrip('/')}/chat/completions", headers, payload)
    return resp.json()["choices"][0]["message"]["content"] or ""


def _call_gemini(model: str, image_b64: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": TRANSCRIBE_PROMPT},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
            ],
        }],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2000},
    }
    headers = {"x-goog-api-key": settings.LLM_API_KEY}
    resp = _post(url, headers, payload)
    candidates = resp.json().get("candidates", [])
    if candidates and candidates[0].get("content", {}).get("parts"):
        return candidates[0]["content"]["parts"][0].get("text", "")
    return ""


def transcribe_page(pil_image) -> str:
    """Transcribe a page image with the vision model. Returns "" if unavailable or on error."""
    if not is_available():
        return ""
    provider = settings.LLM_PROVIDER
    model = _vision_model()
    try:
        image_b64 = _encode_jpeg(pil_image)
        if provider == "gemini":
            text = _call_gemini(model, image_b64)
        elif provider == "groq":
            text = _call_openai_compatible("https://api.groq.com/openai/v1", model, image_b64)
        else:
            text = _call_openai_compatible(settings.LLM_BASE_URL or "https://api.openai.com/v1", model, image_b64)
        return _THINK_RE.sub("", text).strip()
    except Exception as e:
        logger.warning(f"Vision transcription failed ({provider}/{model}): {e}")
        return ""
