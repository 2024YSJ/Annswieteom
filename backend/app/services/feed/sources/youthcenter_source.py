from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import httpx

from app.core.config import settings
from app.services.feed.sources.base import FeedItemData, FeedSource

_ENDPOINT = "https://www.youthcenter.go.kr/opi/youthPlcyList.do"
_FETCH_LIMIT = 20


class YouthCenterApiError(Exception):
    """온통청년이 정상 목록 대신 오류를 돌려준 경우.

    워크넷과 같은 공공 API 계열이라 **HTTP 200 본문에 오류를 담아 보낼 수 있다고
    가정하고** 방어한다(job_info_client.WorknetApiError와 같은 이유 —
    resp.raise_for_status()로는 못 잡는다).
    """

    def __init__(self, message: str | None) -> None:
        self.message = message
        super().__init__(f"youthcenter_api_error: {message}")


def _text(item: ET.Element, *tags: str) -> str:
    """후보 태그를 순서대로 시도해 먼저 잡히는 값을 돌려준다.

    응답 필드명이 아직 실측으로 확정되지 않아서(클래스 docstring 참고) 흔히
    쓰이는 이름 몇 개를 후보로 둔다. 실 응답을 확인하면 후보 목록을 정답
    하나로 줄인다.
    """
    for tag in tags:
        found = item.find(tag)
        if found is not None and found.text and found.text.strip():
            return found.text.strip()
    return ""


def _check_error(root: ET.Element) -> None:
    # ElementTree 요소는 자식이 없으면 텍스트가 있어도 falsy다 — 반드시
    # `is not None`으로 확인한다(job_info_client._check_error가 주석으로
    # 남겨둔 바로 그 함정).
    for tag in ("errMsg", "resultMsg", "message", "error"):
        el = root.find(tag)
        if el is not None and el.text and el.text.strip():
            text = el.text.strip()
            if text in ("SUCCESS", "정상", "정상처리"):
                continue
            raise YouthCenterApiError(text)


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        try:
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _parse_policy_items(root: ET.Element) -> list[FeedItemData]:
    """응답 XML을 FeedItemData로. **필드명 접근은 전부 이 함수 안에서만 일어난다.**

    실 인증키로 응답을 받아본 뒤 고쳐야 할 범위를 여기 하나로 가둬 두려는
    의도다. 모듈의 나머지(호출, 오류 감지, 미설정 시 스킵)는 필드명이 뭐든
    그대로 맞다.

    아이템 엘리먼트의 태그명도 미확정이라 태그로 특정하지 않고 "정책명에
    해당하는 자식을 가진 엘리먼트"를 아이템으로 본다.
    """
    items: list[FeedItemData] = []
    for el in root.iter():
        title = _text(el, "polyBizSjnm", "plcyNm", "policyName")
        if not title:
            continue
        summary = _text(el, "polyItcnCn", "plcyExplnCn", "sporCn", "plcySprtCn")
        org = _text(el, "cnsgNmor", "sprvsnInstCdNm", "operInstCdNm")
        period = _text(el, "rqutPrdCn", "aplyYmd", "bizPrdCn")
        meta = [
            m
            for m in [
                f"운영: {org}" if org else "",
                f"신청: {period}" if period else "",
                summary,
            ]
            if m
        ]
        items.append(
            FeedItemData(
                source="youthcenter",
                category="youth_policy",
                title=title,
                subtitle=org,
                meta_lines=meta,
                detail_url=_text(el, "rqutUrla", "aplyUrlAddr", "refUrlAddr1") or None,
                source_key=_text(el, "bizId", "plcyNo", "policyId") or None,
                source_published_at=_parse_date(_text(el, "frstRegDt", "regDt", "firstRegDt")),
            )
        )
    return items


class YouthCenterFeedSource:
    """온통청년(청년정책 통합) Open API 소스.

    ⚠️ **응답 스키마 미검증.** 확인된 것은 여기까지다: 엔드포인트
    `https://www.youthcenter.go.kr/opi/youthPlcyList.do`, 파라미터
    `openApiVlak`(인증키)/`pageIndex`/`display`, 응답은 XML, 인증키는 회원가입 후
    [마이페이지 - OPEN API]에서 신청해 **담당자 승인**을 거쳐 발급된다(워크넷과
    같은 사람 심사 게이트).

    확인 안 된 것: 응답 엘리먼트/필드 이름 전부, 안정적인 정책 id의 존재 여부,
    오류 응답의 형태, 등록일 필드의 이름과 존재 여부. 그래서 `_parse_policy_items`가
    후보 태그를 여러 개 시도하는 형태이고, 파서 테스트는 인증키가 나오기 전까지
    xfail이다.

    **실 키가 나오면 첫 작업은 curl로 진짜 응답을 받아 테스트에 상수로 붙여넣고
    후보 목록을 정답 하나로 줄이는 것이다** — devlog 15에서 코드값을 짐작했다가
    겪은 실패를 반복하지 않는다.
    """

    name = "youthcenter"
    categories = ("youth_policy",)

    def is_configured(self) -> bool:
        return bool(settings.youthcenter_api_key)

    def is_category_configured(self, category: str) -> bool:
        return self.is_configured()

    async def fetch(self, category: str) -> list[FeedItemData]:
        params = {
            "openApiVlak": settings.youthcenter_api_key,
            "pageIndex": "1",
            "display": str(_FETCH_LIMIT),
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_ENDPOINT, params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        _check_error(root)
        return _parse_policy_items(root)


_typecheck: FeedSource = YouthCenterFeedSource()
