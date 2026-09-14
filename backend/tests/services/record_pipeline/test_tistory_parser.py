from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.services.record_pipeline.parsers import tistory


def _mock_get(html: str):
    async def fake_get(self, url, *args, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(200, text=html, request=request)

    return fake_get


@pytest.mark.asyncio
async def test_known_selector_parses_successfully(monkeypatch):
    html = """
    <html><body>
      <div class="article-view">
        <time datetime="2026-03-15T10:00:00+09:00"></time>
        <p>티스토리 근무 기록 본문입니다</p>
      </div>
    </body></html>
    """
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get(html))

    text, pub_date = await tistory.parse("https://someone.tistory.com/123")

    assert "티스토리 근무 기록 본문입니다" in text
    assert pub_date == date(2026, 3, 15)


@pytest.mark.asyncio
async def test_alternate_selector_also_matches(monkeypatch):
    """네 개 셀렉터 중 첫 번째만 테스트하면 나머지가 깨져도 못 잡는다 — 스킨마다
    다른 셀렉터(`#article-view-content-div`)도 확인한다."""
    html = '<html><body><div id="article-view-content-div">본문 내용</div></body></html>'
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get(html))

    text, pub_date = await tistory.parse("https://someone.tistory.com/456")

    assert "본문 내용" in text
    assert pub_date is None  # 날짜 태그가 아예 없으면 None이어야 한다


@pytest.mark.asyncio
async def test_no_known_selector_falls_back_to_generic_parse(monkeypatch):
    """스킨이 네 셀렉터 중 어디에도 안 걸리면(신규/커스텀 스킨) 조용히 실패하는
    대신 generic.py(trafilatura)로 폴백해야 한다 — velog 이후 세 번째 플랫폼이라
    스킨 다양성이 velog보다 훨씬 크다."""
    html = "<html><body><div class='unknown-skin-wrapper'>본문</div></body></html>"
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get(html))

    async def fake_generic_parse(url):
        return "generic으로 뽑아낸 본문", date(2026, 1, 1)

    monkeypatch.setattr(tistory, "generic_parse", fake_generic_parse)

    text, pub_date = await tistory.parse("https://someone.tistory.com/789")

    assert text == "generic으로 뽑아낸 본문"
    assert pub_date == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_selector_matches_but_empty_text_falls_back_to_generic(monkeypatch):
    """셀렉터는 있는데(빈 컨테이너) 텍스트가 없는 경우도 폴백해야 한다 —
    "셀렉터 존재"와 "실제 본문 존재"는 다른 조건이다."""
    html = '<html><body><div class="contents_style">   </div></body></html>'
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get(html))

    async def fake_generic_parse(url):
        return "generic 폴백 본문", None

    monkeypatch.setattr(tistory, "generic_parse", fake_generic_parse)

    text, pub_date = await tistory.parse("https://someone.tistory.com/999")

    assert text == "generic 폴백 본문"
    assert pub_date is None
