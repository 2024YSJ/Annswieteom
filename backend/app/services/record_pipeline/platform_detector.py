from __future__ import annotations

import re
from urllib.parse import urlparse


def detect_platform(url: str) -> str:
    """Return one of: naver | tistory | velog | brunch | other."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "other"

    if re.search(r"(blog\.naver\.com|m\.blog\.naver\.com)", host):
        return "naver"
    if re.search(r"\.tistory\.com", host):
        return "tistory"
    if host in ("velog.io", "www.velog.io"):
        return "velog"
    if host in ("brunch.co.kr", "www.brunch.co.kr"):
        return "brunch"
    return "other"
