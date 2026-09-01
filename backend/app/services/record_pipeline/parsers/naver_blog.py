from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

_DATE_PATTERN = re.compile(r"(\d{4})[.\-. ](\d{1,2})[.\-. ](\d{1,2})")


def _extract_postview_url(html: str, base_url: str) -> str | None:
    """Find the iframe src that contains the actual blog post HTML."""
    soup = BeautifulSoup(html, "lxml")
    frame = soup.find("iframe", id="mainFrame")
    if not frame:
        return None
    src = frame.get("src", "")
    if not src:
        return None
    if src.startswith("http"):
        return src
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://blog.naver.com{src}"


async def parse(url: str) -> tuple[str, date | None]:
    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        outer_html = resp.text

    postview_url = _extract_postview_url(outer_html, str(resp.url))
    if not postview_url:
        raise ValueError(f"Cannot find mainFrame iframe in {url}. May be a private post.")

    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS, follow_redirects=True) as client:
        resp2 = await client.get(postview_url)
        resp2.raise_for_status()
        inner_html = resp2.text

    soup = BeautifulSoup(inner_html, "lxml")

    body = (
        soup.select_one(".se-main-container")   # smart editor 3
        or soup.select_one("#postViewArea")      # old editor
        or soup.select_one(".post-view")
    )
    if not body:
        raise ValueError(f"No content container found in naver post {url}")

    text = body.get_text(separator="\n", strip=True)
    if not text.strip():
        raise ValueError(f"Empty content in naver post {url}")

    pub_date: date | None = None
    date_tag = (
        soup.select_one(".se_publishDate")
        or soup.select_one(".date")
        or soup.select_one(".blog_post_date")
    )
    if date_tag:
        m = _DATE_PATTERN.search(date_tag.get_text())
        if m:
            try:
                pub_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

    return text.strip(), pub_date
