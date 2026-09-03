from __future__ import annotations

import re
from datetime import date

from google import genai
from google.genai import types

from app.core.config import settings

_DATE_PATTERN = re.compile(r"(\d{4})[.\-년 ](\d{1,2})[.\-월 ](\d{1,2})")

MIME_TYPES_BY_EXTENSION = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


async def extract_text_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> tuple[str, date | None]:
    """Use Gemini Vision to extract text and publication date from an image.

    Takes raw bytes rather than a filesystem path — the caller (record_pipeline)
    is responsible for fetching the bytes from wherever the image is stored
    (Supabase Storage in production), keeping this module storage-agnostic.

    Returns (extracted_text, date_if_found).
    """
    client = genai.Client(api_key=settings.gemini_api_key)

    prompt = (
        "이 이미지에서 텍스트를 모두 추출해주세요. "
        "자격증이나 수료증이라면 발급일(YYYY-MM-DD 형식)도 별도로 표시해주세요. "
        "응답 형식: 먼저 추출된 텍스트, 그 다음 줄에 'DATE: YYYY-MM-DD' (날짜가 없으면 생략)."
    )

    try:
        response = await client.aio.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
        )
        raw = response.text or ""
    except Exception as exc:
        raise RuntimeError(f"Gemini OCR failed: {exc}") from exc

    pub_date: date | None = None
    date_match = re.search(r"DATE:\s*(\d{4}-\d{2}-\d{2})", raw)
    if date_match:
        try:
            pub_date = date.fromisoformat(date_match.group(1))
        except ValueError:
            pass

    if not pub_date:
        m = _DATE_PATTERN.search(raw)
        if m:
            try:
                pub_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

    text = re.sub(r"DATE:.*", "", raw).strip()
    return text, pub_date
