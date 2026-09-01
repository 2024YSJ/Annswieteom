from __future__ import annotations

import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from app.services.record_pipeline.parsers.generic import parse as generic_parse

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

_CONTENT_SELECTORS = [
    ".contents_style",
    ".article-view",
    "#article-view-content-div",
    ".tt_article_useless_p_margin",
]

_DATE_PATTERN = re.compile(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})")


async def parse(url: str) -> tuple[str, date | None]:
    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")

    body = None
    for selector in _CONTENT_SELECTORS:
        body = soup.select_one(selector)
        if body:
            break

    if not body:
        return await generic_parse(url)

    text = body.get_text(separator="\n", strip=True)
    if not text.strip():
        return await generic_parse(url)

    pub_date: date | None = None
    time_tag = soup.find("time") or soup.find(class_=re.compile(r"date|time|published", re.I))
    if time_tag:
        raw = time_tag.get("datetime", "") or time_tag.get_text()
        m = _DATE_PATTERN.search(str(raw))
        if m:
            try:
                pub_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

    return text.strip(), pub_date
