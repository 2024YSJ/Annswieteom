from __future__ import annotations

from datetime import date

import httpx
import trafilatura


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


async def parse(url: str) -> tuple[str, date | None]:
    """Return (body_text, published_date). Raises on failure."""
    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    if not text.strip():
        raise ValueError(f"No extractable text from {url}")

    pub_date: date | None = None
    meta = trafilatura.extract_metadata(html)
    if meta and meta.date:
        try:
            pub_date = date.fromisoformat(meta.date[:10])
        except (ValueError, TypeError):
            pass

    return text.strip(), pub_date
