from __future__ import annotations

import logging
import re
from datetime import date, datetime

import httpx

from app.core.config import settings
from app.services.feed import youthcenter_codes as yc
from app.services.feed.sources.base import FeedItemData, FeedSource

logger = logging.getLogger(__name__)

#: 2026-09-09 실 인증키로 확인한 엔드포인트. 예전에 문서에서 유추해 써뒀던
#: `/opi/youthPlcyList.do`(XML)는 **죽어 있다** — 같은 호스트인데 이 경로만
#: 연결이 타임아웃된다(도메인 루트는 200). 실제로 살아 있는 건 이쪽이고
#: 응답은 XML이 아니라 JSON이다.
_ENDPOINT = "https://www.youthcenter.go.kr/go/ythip/getPlcy"

#: 페이지 크기와 최대 페이지 수. 전체는 2,700여 건이고 API가 등록 최신순으로
#: 돌려주므로(실측 확인) 앞쪽부터 받는다. pageSize=100까지는 정상 동작한다.
#: 예전엔 최신 100건만 받았다(카드 목록용으로는 충분했다). 티어 매칭을 붙이면서
#: 10페이지로 넓혔다 — **풀이 좁으면 교집합 칸이 텅 빈다.** 사용자 거주지·나이에
#: 맞는 정책이 최신 100건 안에는 몇 개 없다. 마감이 지난 정책은 버린다.
_PAGE_SIZE = 100
_MAX_PAGES = 10


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


def _codes(item: dict, key: str) -> list[str]:
    return [c.strip() for c in _text(item, key).split(",") if c.strip()]


def _int(item: dict, key: str) -> int:
    try:
        return int(_text(item, key) or 0)
    except ValueError:
        return 0


def _today() -> date:
    """마감 판정 기준일. 테스트가 날짜를 고정할 수 있게 한 겹 둔다."""
    return date.today()


def _is_expired(item: dict, today: date) -> bool:
    """신청기간(`aplyYmd` "20260701 ~ 20260713")의 끝이 오늘 이전인가.

    상시모집이면 비어 있다 — 그건 마감이 아니다. 형식이 이상하면 버리지 않는다
    (모르는 걸 마감으로 치면 멀쩡한 정책이 사라진다).
    """
    dates = re.findall(r"\d{8}", _text(item, "aplyYmd"))
    if not dates:
        return False
    try:
        end = max(datetime.strptime(d, "%Y%m%d").date() for d in dates)
    except ValueError:
        return False
    return end < today


def _parse_eligibility(item: dict) -> dict:
    """자격조건 필드를 매칭용 dict로. 코드는 원형 그대로 둔다 — 라벨 변환은
    youthcenter_codes가, 판정은 services/feed/matching.py가 한다.

    `sprtTrgtAgeLmtYn`은 쓰지 않는다. 실측에서 Y·N 모두 실제 연령 범위와 함께
    왔고(Y 19~39, N 19~39 둘 다 흔하다) Y+0/0이 "제한없음"이었다 — 연령 제한 여부는
    min/max가 0이 아닌지로만 판단한다.
    """
    zips = _codes(item, "zipCd")
    nationwide = len(zips) >= yc.NATIONWIDE_ZIP_COUNT
    lo, hi = _int(item, "sprtTrgtMinAge"), _int(item, "sprtTrgtMaxAge")
    earn_cond = _text(item, "earnCndSeCd") or None
    return {
        "age": {"min": lo, "max": hi} if (lo or hi) else None,
        # 전국 대상이면 250여 개 코드를 통째로 담을 이유가 없다.
        "zip_codes": [] if nationwide else zips,
        "nationwide": nationwide,
        "school": _codes(item, "schoolCd"),
        "major": _codes(item, "plcyMajorCd"),
        "job_status": _codes(item, "jobCd"),
        "special": _codes(item, "sbizCd"),
        "marital": _text(item, "mrgSttsCd") or None,
        "income": (
            {"cond": earn_cond, "min": _int(item, "earnMinAmt"), "max": _int(item, "earnMaxAmt")}
            if earn_cond
            else None
        ),
    }


def _parse_policy_items(payload: dict, today: date | None = None) -> list[FeedItemData]:
    """응답 JSON을 FeedItemData로. 필드 접근은 전부 이 함수 안에서만 일어난다.

    2026-09-09 실 응답(60개 필드)을 보고 확정했다. 이전 버전은 문서에서 유추한
    이름(`polyBizSjnm`, `cnsgNmor`, `rqutPrdCn` 등)을 후보로 여러 개 시도하는
    구조였는데, 실제 스키마와 대부분 달랐다.
    """
    items: list[FeedItemData] = []
    today = today or date.today()
    for raw in (payload.get("result") or {}).get("youthPolicyList", []) or []:
        title = _text(raw, "plcyNm")
        if not title:
            continue
        if _is_expired(raw, today):
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
                eligibility=_parse_eligibility(raw),
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
        items: list[FeedItemData] = []
        seen: set[str] = set()
        today = _today()
        async with httpx.AsyncClient(timeout=20.0) as client:
            for page in range(1, _MAX_PAGES + 1):
                try:
                    payload = await self._fetch_page(client, page)
                except (YouthCenterApiError, ValueError) as exc:
                    if page == 1:
                        raise
                    # 온통청년은 가끔 한 페이지만 400(api data invalid)이나
                    # 403(invalid api key)을 낸다 — 같은 키로 앞뒤 페이지는 성공하고,
                    # 실패하는 페이지가 매번 다르다(2026-09-11 실측 세 번: 14, 15, 2).
                    # 이미 받은 페이지까지 버릴 이유는 없다.
                    logger.warning("youthcenter: page %d failed (%s); keeping %d item(s)", page, exc, len(items))
                    break
                raw_list = (payload.get("result") or {}).get("youthPolicyList", []) or []
                for item in _parse_policy_items(payload, today):
                    # 페이지 사이에 새 정책이 등록되면 한 칸씩 밀려 같은 정책이
                    # 두 페이지에 걸쳐 나온다.
                    key = item.source_key or item.title
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(item)
                if len(raw_list) < _PAGE_SIZE:
                    break
        return items

    async def _fetch_page(self, client: httpx.AsyncClient, page: int) -> dict:
        params = {
            "apiKeyNm": settings.youthcenter_api_key,
            "pageNum": str(page),
            "pageSize": str(_PAGE_SIZE),
            "rtnType": "json",
        }
        try:
            resp = await client.get(_ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            # httpx 예외 메시지에는 요청 URL — 즉 쿼리스트링의 인증키 — 가 통째로
            # 들어 있다. 그대로 올리면 ingest가 last_error에 저장하고 /feed/sources가
            # 로그인 사용자에게 보여준다. 예외 종류만 남기고 원인 체인도 끊는다.
            raise YouthCenterApiError(type(exc).__name__, "transport error") from None
        if resp.status_code >= 400:
            # raise_for_status()도 같은 이유로 쓰지 않는다(메시지에 URL이 들어간다).
            raise YouthCenterApiError(resp.status_code, resp.text[:120])
        payload = resp.json()

        # HTTP 200이어도 본문 resultCode로 실패가 온다.
        code = payload.get("resultCode")
        if code != 200:
            raise YouthCenterApiError(code, payload.get("resultMessage"))
        return payload


_typecheck: FeedSource = YouthCenterFeedSource()
