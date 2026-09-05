from __future__ import annotations

import httpx
import pytest

from app.services.record_pipeline.parsers import naver_blog

_OUTER_HTML_WITH_IFRAME = """
<html><body>
<iframe id="mainFrame" src="/PostView.naver?blogId=someone&logNo=123"></iframe>
</body></html>
"""


def _mock_get(responses):
    calls = []

    async def fake_get(self, url, *args, **kwargs):
        calls.append(url)
        text = responses[len(calls) - 1]
        request = httpx.Request("GET", url)
        return httpx.Response(200, text=text, request=request)

    return fake_get, calls


@pytest.mark.asyncio
async def test_private_post_with_missing_content_container_raises_private_hint(monkeypatch):
    """Naver still serves the mainFrame iframe fine for a private post (so
    that check passes) — the inner page it points to is a "this post is
    private" placeholder with none of the three known content selectors, not
    an HTTP error. The raised message must mention "private" so
    pipeline.py's _user_message() shows the correct guidance instead of a
    generic, unhelpful error (regression test for the 2026-09-05 fix)."""
    inner_html_without_any_selector = "<html><body><div class='private-notice'>이 포스트는 비공개입니다</div></body></html>"
    fake_get, calls = _mock_get([_OUTER_HTML_WITH_IFRAME, inner_html_without_any_selector])
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(ValueError, match="[Pp]rivate"):
        await naver_blog.parse("https://blog.naver.com/someone/123")

    assert len(calls) == 2  # fetched both the outer page and the inner iframe page


@pytest.mark.asyncio
async def test_normal_post_with_content_parses_successfully(monkeypatch):
    inner_html = '<html><body><div class="post-view">근무 기록 본문입니다</div></body></html>'
    fake_get, _ = _mock_get([_OUTER_HTML_WITH_IFRAME, inner_html])
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    text, pub_date = await naver_blog.parse("https://blog.naver.com/someone/123")
    assert "근무 기록 본문입니다" in text
    assert pub_date is None
