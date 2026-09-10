from __future__ import annotations

from datetime import date, datetime

import httpx

from app.core.config import settings
from app.services.feed.sources.base import FeedItemData, FeedSource

#: 2026-09-09 실 인증키로 확인한 엔드포인트. 예전에 문서에서 유추해 써뒀던
#: `/opi/youthPlcyList.do`(XML)는 **죽어 있다** — 같은 호스트인데 이 경로만
#: 연결이 타임아웃된다(도메인 루트는 200). 실제로 살아 있는 건 이쪽이고
#: 응답은 XML이 아니라 JSON이다.
_ENDPOINT = "https://www.youthcenter.go.kr/go/ythip/getPlcy"

#: 한 번에 받아올 정책 수. 전체는 2751건이고 API가 이미 등록 최신순으로
#: 돌려주므로(실측 확인) 앞쪽만 받으면 된다. pageSize=100까지는 정상 동작한다.
#: 메인 화면에 "더보기"를 붙이면서 30에서 올렸다 — 30이면 정책 섹션이 다섯 번쯤
#: 누르면 바닥났다.
_FETCH_LIMIT = 100


class YouthCenterApiError(Exception):
    """온통청년이 정상 목록 대신 오류를 돌려준 경우.

    이 API는 HTTP 200으로 응답하면서 본문 `resultCode`로 성공/실패를 구분한다
    (고용24과 같은 계열의 함정 — `raise_for_status()`로는 못 잡는다).
    """

    def __init__(self, code: object, message: str | None) -> None:
        self.code = code
        self.message = message
        super().__init__(f"youthcenter_api_error({code}): {message}")


def _text(item: dict, key: str) -> str:
    value = item.get(key)
    return str(value).strip() if value not in (None, "") else ""


def _parse_reg_date(raw: str) -> date | None:
    """`frstRegDt`는 "2026-09-08 09:13:11" 형태다(YYYYMMDD가 아니다)."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _format_period(item: dict) -> str:
    """신청기간. `aplyYmd`가 "20260701 ~ 20260713" 형태로 오지만 상시모집이면
    비어 있고(그 경우 `aplyPrdSeCd`가 0057002), 그때는 사업기간으로 갈음한다."""
    apply_period = _text(item, "aplyYmd")
    if apply_period:
        return apply_period.replace("~", "~")
    start, end = _text(item, "bizPrdBgngYmd"), _text(item, "bizPrdEndYmd")
    if start or end:
        return f"{start} ~ {end}".strip()
    return ""


def _parse_policy_items(payload: dict) -> list[FeedItemData]:
    """응답 JSON을 FeedItemData로. 필드 접근은 전부 이 함수 안에서만 일어난다.

    2026-09-09 실 응답(60개 필드)을 보고 확정했다. 이전 버전은 문서에서 유추한
    이름(`polyBizSjnm`, `cnsgNmor`, `rqutPrdCn` 등)을 후보로 여러 개 시도하는
    구조였는데, 실제 스키마와 대부분 달랐다.
    """
    items: list[FeedItemData] = []
    for raw in payload.get("result", {}).get("youthPolicyList", []) or []:
        title = _text(raw, "plcyNm")
        if not title:
            continue

        org = _text(raw, "sprvsnInstCdNm")  # 주관기관(시·도, 부처 등)
        operator = _text(raw, "operInstCdNm")  # 운영기관(대학, 센터 등)
        large, medium = _text(raw, "lclsfNm"), _text(raw, "mclsfNm")
        period = _format_period(raw)
        summary = _text(raw, "plcySprtCn") or _text(raw, "plcyExplnCn")

        classification = " · ".join(p for p in (large, medium) if p)
        meta = [
            m
            for m in (
                f"분류: {classification}" if classification else "",
                f"신청: {period}" if period else "",
                f"운영: {operator}" if operator and operator != org else "",
                # 지원 내용은 줄바꿈이 섞인 긴 원문이라 카드에서 잘라 보여준다.
                " ".join(summary.split())[:180] if summary else "",
            )
            if m
        ]

        items.append(
            FeedItemData(
                source="youthcenter",
                category="youth_policy",
                title=title,
                subtitle=org,
                meta_lines=meta,
                # 신청 URL이 없는 정책도 많아 참고 URL로 갈음한다.
                detail_url=_text(raw, "aplyUrlAddr") or _text(raw, "refUrlAddr1") or None,
                # plcyNo는 정책 고유번호라 안정적인 중복 제거 키가 된다 —
                # 고용24 카테고리 대부분이 못 주는 것이다.
                source_key=_text(raw, "plcyNo") or None,
                source_published_at=_parse_reg_date(_text(raw, "frstRegDt")),
            )
        )
    return items


class YouthCenterFeedSource:
    """온통청년(청년정책 통합) Open API 소스.

    인증키는 회원가입 후 [마이페이지 - OPEN API]에서 신청해 담당자 승인을 거쳐
    발급된다(고용24과 같은 사람 심사 게이트). 비어 있으면 이 소스는 오류가 아니라
    수집 대상에서 조용히 빠진다(services/feed/sources/__init__.py).

    **분류로 걸러내지 않는다.** 대분류는 일자리/교육･직업훈련/금융･복지･문화/
    참여･기반/주거 다섯 가지이고, 취업 관련(일자리+교육･직업훈련)은 절반쯤이다.
    그래도 전부 받는 이유는 섹션 이름이 "취업 정책"이 아니라 "청년 지원 정책"이고,
    공백기 청년에게 월세·금융 지원도 실제로 쓸모가 있기 때문이다. 대신 분류를
    meta_lines 첫 줄에 실어 카드에서 바로 구분되게 했다.
    """

    name = "youthcenter"
    categories = ("youth_policy",)

    def is_configured(self) -> bool:
        return bool(settings.youthcenter_api_key)

    def is_category_configured(self, category: str) -> bool:
        return self.is_configured()

    async def fetch(self, category: str) -> list[FeedItemData]:
        params = {
            "apiKeyNm": settings.youthcenter_api_key,
            "pageNum": "1",
            "pageSize": str(_FETCH_LIMIT),
            "rtnType": "json",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_ENDPOINT, params=params)
            resp.raise_for_status()
            payload = resp.json()

        # HTTP 200이어도 본문 resultCode로 실패가 온다.
        code = payload.get("resultCode")
        if code != 200:
            raise YouthCenterApiError(code, payload.get("resultMessage"))

        return _parse_policy_items(payload)


_typecheck: FeedSource = YouthCenterFeedSource()
