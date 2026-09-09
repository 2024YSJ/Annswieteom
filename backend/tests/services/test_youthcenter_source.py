from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services.feed.sources import configured_sources
from app.services.feed.sources.youthcenter_source import (
    YouthCenterApiError,
    YouthCenterFeedSource,
)

# ⚠️ 아래 XML은 **실측 응답이 아니라 문서에서 유추한 모양**이다. 인증키가
# 발급되면 첫 작업은 curl로 진짜 응답을 받아 이 상수를 통째로 교체하고,
# youthcenter_source._text의 후보 태그 목록을 정답 하나로 줄이는 것이다.
# 그때까지 파싱 테스트는 xfail로 둔다 — 지어낸 필드명으로 초록 테스트를
# 만들어두면 "검증됐다"는 거짓 신호가 된다(devlog 15에서 코드값을 짐작했다가
# 겪은 실패와 같은 종류).
_PLACEHOLDER_POLICY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<youthPolicyList>
  <youthPolicy>
    <bizId>R2026010112345</bizId>
    <polyBizSjnm>청년월세 한시 특별지원</polyBizSjnm>
    <polyItcnCn>무주택 청년에게 월 최대 20만원을 12개월간 지원합니다.</polyItcnCn>
    <cnsgNmor>국토교통부</cnsgNmor>
    <rqutPrdCn>2026-03-01 ~ 2026-12-31</rqutPrdCn>
    <rqutUrla>https://www.myhome.go.kr/youth</rqutUrla>
    <frstRegDt>20260301</frstRegDt>
  </youthPolicy>
</youthPolicyList>
"""

_ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<youthPolicyList>
  <errMsg>인증키가 유효하지 않습니다.</errMsg>
</youthPolicyList>
"""


def _mock_get(monkeypatch, xml_text: str, status_code: int = 200):
    async def fake_get(self, url, params=None, **kwargs):
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(status_code, text=xml_text, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


def test_source_is_not_configured_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "youthcenter_api_key", "")
    assert YouthCenterFeedSource().is_configured() is False


def test_source_is_configured_with_a_key(monkeypatch):
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    assert YouthCenterFeedSource().is_configured() is True


def test_unconfigured_source_is_silently_dropped_from_the_registry(monkeypatch):
    """키 미발급은 오류가 아니라 설정 상태다 — 예외를 던지면 승인될 때까지
    메인 화면에 빨간 배너가 계속 뜬다."""
    monkeypatch.setattr(settings, "youthcenter_api_key", "")
    names = [s.name for s in configured_sources()]
    assert "youthcenter" not in names
    # 워크넷은 그대로 살아 있어야 한다.
    assert "worknet" in names


@pytest.mark.asyncio
async def test_error_body_with_http_200_raises(monkeypatch):
    """워크넷과 같은 계열이라 오류일 때도 HTTP 200이 올 수 있다고 가정한다 —
    raise_for_status로는 못 잡는다."""
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    _mock_get(monkeypatch, _ERROR_XML)
    with pytest.raises(YouthCenterApiError):
        await YouthCenterFeedSource().fetch("youth_policy")


@pytest.mark.xfail(reason="온통청년 인증키 미발급 — 응답 필드명이 실측으로 확정되지 않았다", strict=False)
@pytest.mark.asyncio
async def test_parses_a_policy_response(monkeypatch):
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    _mock_get(monkeypatch, _PLACEHOLDER_POLICY_XML)

    results = await YouthCenterFeedSource().fetch("youth_policy")

    assert len(results) == 1
    item = results[0]
    assert item.title == "청년월세 한시 특별지원"
    assert item.source == "youthcenter"
    assert item.category == "youth_policy"
    assert item.feed_kind == "policy"
    assert item.source_key == "R2026010112345"
    assert item.detail_url == "https://www.myhome.go.kr/youth"
    assert item.source_published_at is not None
    assert any("국토교통부" in m for m in item.meta_lines)
