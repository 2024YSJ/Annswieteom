from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from app.core.config import settings
from app.services.job_pipeline.regions import RegionFilter, resolve_region_filters
from app.services.llm.base import JobInfoQueryParams

logger = logging.getLogger(__name__)

# 훈련과정 조회는 날짜 범위가 필수인데(공식 명세) 사용자 질문에서 날짜를
# 뽑아내는 건 이번 범위 밖이라(devlog 16 계획 참고) 항상 "오늘부터 90일"로
# 고정한다 — 곧 시작하는/모집 중인 과정 위주로 보여주는 셈이라 실용적인 기본값.
_TRAINING_WINDOW_DAYS = 90

# 카테고리당 고용24에서 받아오는 원본 건수 상한 — 이 목록 전체가 그대로
# select_relevant_job_info_results 프롬프트에 들어가므로(devlog 18: 문자열
# 부분일치 대신 LLM이 실제로 관련 있는 항목을 골라내는 방식으로 교체), 로컬
# LLM 호출 하나에 무리 없이 들어갈 만큼만 가져온다.
_FETCH_LIMIT = 20
#: 서버 측 필터가 없는 카테고리(아래 _FILTERABLE_CATEGORIES 주석 참고)는 후보
#: 풀이 좁으면 select_relevant_job_info_results가 고를 게 없다 — 필터 대신
#: 후보를 조금 더 넓게 받는다. 이 목록 전체가 로컬 LLM 프롬프트에 그대로
#: 들어가므로 무제한으로 늘리지 않는다(지연시간 증가).
_UNFILTERED_FETCH_LIMIT = 30
_TRAINING_PER_ENDPOINT_LIMIT = 10

# 권역 질문("경기 북부")은 광역으로 조회한 뒤 주소로 걸러내므로, 기본 10건만
# 받으면 경기 첫 10건이 전부 남부일 때 북부 결과가 0건이 된다.
_TRAINING_GROUP_PAGE_SIZE = 30

# 같은 파라미터에 값을 여러 개 넣는 건 API가 지원하지 않아(콤마는 0건, 반복
# 파라미터는 첫 값만 적용) 값마다 호출을 쪼갠다. 곱집합을 그대로 두면 훈련과정은
# 엔드포인트가 4개라 호출이 수십 회로 폭발하므로 각 차원과 조합 수에 상한을 둔다.
_MAX_REGION_FILTERS = 3
_MAX_KEYWORDS = 2
_MAX_TRAINING_COMBOS = 3

# 조건을 다 걸었을 때 이보다 적게 남으면 키워드를 떼고 지역만으로 한 번 더
# 넓힌다 — 실측(devlog 20)에서 "경기 북부 + 자바/웹 개발"이 2건이었는데
# 지역만으로는 4건이었다. 과정명에 그 키워드가 안 들어간 과정이 통째로 빠진
# 것이라, 정밀도를 조금 내주고 재현율을 되찾는 편이 낫다.
_MIN_RESULTS_BEFORE_WIDENING = 5

# 조회 조건을 실을 수 있다고 확인된 카테고리.
# - training_course(hr/* 4개 엔드포인트): srchTraArea1/srchTraArea2/srchTraProcessNm
#   반영 확인(devlog 20).
# - job_fair(callOpenApiSvcInfo210L11.do): keyword가 eventNm(행사명) 부분일치로
#   반영되는 것을 실측 확인(2026-09-13). 지역 계열 파라미터는 후보 9개를 시도했지만
#   못 찾음.
# - promising_sme(callOpenApiSvcInfo216L01.do): region=<광역 2자리>000(5자리, 예:
#   경기 "41000")이 반영되는 것을 실측 확인(2026-09-13). 직무/키워드 계열은
#   후보 9개를 시도했지만 못 찾음.
# 나머지 2개(public_recruitment, public_recruitment_company)는 지역 후보 9개·직무
# 후보 8~9개를 전부 시도했지만(2026-09-13) 반영되는 파라미터를 찾지 못했다.
# job_seeker_program은 그날 응답 자체가 0건이라 검증이 원천적으로 불가능했다 —
# 재실측이 필요하다. 이 3개는 필터를 못 걸고 대신 후보 풀만 넓힌다
# (_UNFILTERED_FETCH_LIMIT).
_FILTERABLE_CATEGORIES = frozenset({"training_course", "job_fair", "promising_sme"})


class WorknetApiError(Exception):
    """고용24가 정상 목록 대신 오류 응답을 돌려준 경우(인증키 미승인,
    개인회원 계정 차단 등). 이 API들은 오류일 때도 HTTP 200을 주고 본문에만
    오류 내용을 담아 보내므로 `resp.raise_for_status()`로는 못 잡는다 — 이걸
    구분 안 하면 "검색 결과 없음"과 "API 자체가 실패함"이 똑같이 보인다(실제로
    겪은 문제, devlog 15). 관찰된 오류 응답 형태가 최소 두 가지 —
    `<wantedRoot><message>.../<messageCd>...`와 `<GO24><error>...` — 둘 다
    감지한다."""

    def __init__(self, category: str, message: str | None) -> None:
        self.category = category
        self.message = message
        super().__init__(f"worknet_api_error({category}): {message}")


#: 고용24 채용행사 상세 페이지. 파라미터 이름이 API 필드명과 다르다 —
#: API가 주는 eventNo/areaCd가 화면에서는 newsDataSeqno/eventMegaRegionCd다
#: (2026-09-10 실제 행사 두 건으로 확인).
_EMP_EVENT_DETAIL_URL = "https://www.work24.go.kr/wk/a/f/1100/retrieveEmpEventDtl.do"


@dataclass
class JobInfoResult:
    """6개 카테고리 전부가 공유하는 결과 모양 — 각 고용24 API의 XML 필드가
    전부 다르므로(카테고리별 파서 참고) 프론트가 카테고리 상관없이 카드 하나로
    그릴 수 있게 여기서 정규화한다."""
    title: str
    subtitle: str
    meta_lines: list[str]
    detail_url: str | None = None
    #: 소스가 주는 항목 고유 id. 피드의 중복 제거 키로 쓰인다(feed/dedup.py) —
    #: 없으면 내용 해시로 갈음하는데, 그러면 소스가 문구를 한 글자만 고쳐도
    #: 새 항목으로 들어온다. 카테고리마다 id 필드 이름이 다르므로 파서에서 채운다.
    source_key: str | None = None
    #: 개설 지역의 시군구 코드(훈련과정의 `trngAreaCd`, 예 "41285"). 맞춤 직업훈련이
    #: 사용자 거주지·희망지역과 비교해 가까운 과정을 먼저 올리는 데 쓴다.
    region_code: str | None = None


def _text(item: ET.Element, tag: str) -> str:
    found = item.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _check_error(root: ET.Element, category: str) -> None:
    # `Element.__bool__`은 자식이 없는 요소면 텍스트가 있어도 False라, find()
    # 결과를 `or`로 이어붙이면 진짜 <message> 매치를 조용히 건너뛸 수 있다 —
    # 반드시 `is not None`으로 명시적으로 확인한다.
    message_el = root.find("message")
    error_text_el = message_el if message_el is not None else root.find("error")
    if error_text_el is not None:
        msg = error_text_el.text.strip() if error_text_el.text else None
        # 고용24가 자기 XML 본문에 실어 보낸 문구 그대로다 — 우리 URL/authKey는
        # 들어 있지 않으므로 그대로 로깅해도 안전하다.
        logger.warning("job_pipeline: %s api error: %s", category, msg)
        raise WorknetApiError(category, msg)


async def _get(url: str, params: dict[str, str], category: str) -> ET.Element:
    # httpx 예외 메시지와 raise_for_status()의 메시지에는 요청 URL — 즉 쿼리스트링의
    # authKey — 가 통째로 들어 있다. 그대로 올리면 피드 수집이 last_error에 저장하고
    # /feed/sources가 로그인 사용자에게 보여준다(온통청년에서 같은 경로를 막은 것과
    # 같은 이유, devlog 31). 상태코드를 직접 보고 URL 없는 WorknetApiError로 바꾼다.
    #
    # 2026-09-12까지는 이 파일에 로깅이 전혀 없어서, 고용24 전면 점검 장애를 API
    # 응답(0건/skipped)만으로는 원인까지 진단할 수 없었다. 아래 두 곳은 카테고리명과
    # 상태코드/예외 종류만 남긴다 — URL·authKey는 절대 포함하지 않는다.
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        logger.warning("job_pipeline: %s transport error: %s", category, type(exc).__name__)
        raise WorknetApiError(category, f"transport error: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        logger.warning("job_pipeline: %s http %s", category, resp.status_code)
        raise WorknetApiError(category, f"http {resp.status_code}")
    root = ET.fromstring(resp.text)
    _check_error(root, category)
    return root


async def search_job_fairs(params: JobInfoQueryParams | None = None, limit: int = _FETCH_LIMIT) -> list[JobInfoResult]:
    request_params = {
        "authKey": settings.worknet_job_posting_api_key, "returnType": "XML", "callTp": "L",
        "startPage": "1", "display": str(limit),
    }
    if params and params.keywords:
        # API는 값 하나만 받는다(training_course와 같은 제약) — 첫 키워드만
        # 싣는다. 여러 키워드를 다 걸어야 하면 training처럼 조합별 호출로
        # 확장한다(지금은 최소 변경).
        request_params["keyword"] = params.keywords[0]
    root = await _get(
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L11.do",
        request_params,
        "job_fair",
    )
    results = []
    for item in root.findall(".//empEvent"):
        term = _text(item, "eventTerm")
        event_no = _text(item, "eventNo")
        area_cd = _text(item, "areaCd")
        # 상세 페이지가 지역 코드까지 요구한다. 둘 중 하나라도 없으면 링크를
        # 만들지 않는다 — 안 열리는 링크는 링크가 없는 것보다 나쁘다.
        detail_url = (
            f"{_EMP_EVENT_DETAIL_URL}?newsDataSeqno={event_no}&eventMegaRegionCd={area_cd}"
            if event_no and area_cd
            else None
        )
        results.append(
            JobInfoResult(
                title=_text(item, "eventNm"),
                subtitle=_text(item, "area"),
                meta_lines=[f"기간: {term}"] if term else [],
                detail_url=detail_url,
                source_key=event_no or None,
            )
        )
    return results


async def search_public_recruitment(limit: int = _UNFILTERED_FETCH_LIMIT) -> list[JobInfoResult]:
    root = await _get(
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L21.do",
        {"authKey": settings.worknet_job_posting_api_key, "returnType": "XML", "callTp": "L", "startPage": "1", "display": str(limit)},
        "public_recruitment",
    )
    results = []
    for item in root.findall(".//dhsOpenEmpInfo"):
        co_size = _text(item, "coClcdNm")
        stdt = _text(item, "empWantedStdt")
        endt = _text(item, "empWantedEndt")
        emp_type = _text(item, "empWantedTypeNm")
        meta = [m for m in [f"규모: {co_size}" if co_size else "", f"기간: {stdt}~{endt}" if stdt or endt else "", f"고용형태: {emp_type}" if emp_type else ""] if m]
        results.append(
            JobInfoResult(
                title=_text(item, "empWantedTitle"),
                subtitle=_text(item, "empBusiNm"),
                meta_lines=meta,
                # 이 카테고리는 고용24 상세 페이지가 아니라 기업이 직접 올린
                # 채용 페이지 주소를 준다. 모바일 주소는 비어 있는 경우가 많아
                # 보조로만 쓴다.
                detail_url=_text(item, "empWantedHomepgDetail") or _text(item, "empWantedMobileUrl") or None,
                source_key=_text(item, "empSeqno") or None,
            )
        )
    return results


async def search_public_recruitment_companies(limit: int = _UNFILTERED_FETCH_LIMIT) -> list[JobInfoResult]:
    root = await _get(
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L31.do",
        {"authKey": settings.worknet_job_posting_api_key, "returnType": "XML", "callTp": "L", "startPage": "1", "display": str(limit)},
        "public_recruitment_company",
    )
    results = []
    for item in root.findall(".//dhsOpenEmpHireInfo"):
        co_size = _text(item, "coClcdNm")
        intro = _text(item, "coIntroSummaryCont")
        meta = [m for m in [f"규모: {co_size}" if co_size else "", intro] if m]
        results.append(
            JobInfoResult(
                title=_text(item, "coNm"),
                subtitle=co_size,
                meta_lines=meta,
                # 고용24에는 이 카테고리의 공개 상세 페이지가 없다(기업정보
                # 상세는 로그인 + 내부 코드가 필요하다). 대신 응답이 기업이
                # 직접 운영하는 채용 홈페이지를 주므로 그리로 보낸다.
                detail_url=_text(item, "homepg") or None,
                source_key=_text(item, "empCoNo") or None,
            )
        )
    return results


async def search_job_seeker_programs(limit: int = _UNFILTERED_FETCH_LIMIT) -> list[JobInfoResult]:
    root = await _get(
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo217L01.do",
        {"authKey": settings.worknet_job_seeker_program_api_key, "returnType": "XML", "callTp": "L", "startPage": "1", "display": str(limit)},
        "job_seeker_program",
    )
    results = []
    for item in root.findall(".//empPgmSchdInvite"):
        name = _text(item, "pgmNm")
        sub_name = _text(item, "pgmSubNm")
        org = _text(item, "orgNm")
        stdt = _text(item, "pgmStdt")
        endt = _text(item, "pgmEndt")
        place = _text(item, "openPlcCont")
        meta = [m for m in [f"운영: {org}" if org else "", f"기간: {stdt}~{endt}" if stdt or endt else "", f"장소: {place}" if place else ""] if m]
        results.append(JobInfoResult(title=name or sub_name, subtitle=sub_name if name else "", meta_lines=meta))
    return results


async def search_promising_smes(params: JobInfoQueryParams | None = None, limit: int = _FETCH_LIMIT) -> list[JobInfoResult]:
    request_params = {
        "authKey": settings.worknet_promising_sme_api_key, "returnType": "XML", "callTp": "L",
        "startPage": "1", "display": str(limit),
    }
    if params and params.regions:
        # 이 엔드포인트는 지역 조건 하나만 받는다(job_fair의 keyword와 같은
        # 최소 변경 원칙) — 5자리(광역 2자리 + "000") 형식이 실측 확인됐다.
        filters = resolve_region_filters(params.regions, limit=1)
        if filters:
            request_params["region"] = f"{filters[0].area1}000"
    root = await _get(
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo216L01.do",
        request_params,
        "promising_sme",
    )
    results = []
    for item in root.findall(".//smallGiant"):
        industry = _text(item, "indTpNm")
        region = _text(item, "regionNm")
        product = _text(item, "coMainProd")
        meta = [m for m in [f"업종: {industry}" if industry else "", f"지역: {region}" if region else "", f"주요생산품: {product}" if product else ""] if m]
        results.append(
            JobInfoResult(
                title=_text(item, "coNm"),
                subtitle=industry,
                meta_lines=meta,
                # 상세 URL 없음 — 응답에 링크 필드가 없고, 고용24의 강소기업
                # 페이지는 제도 안내일 뿐 기업별 상세가 없다(2026-09-10 확인).
                # 추측해서 만든 링크로 보내느니 안 눌리는 카드로 둔다.
                source_key=_text(item, "busiNo") or None,
            )
        )
    return results


# 훈련과정 4종 — 사용자에게는 "직업훈련과정" 하나로 보이지만 실제로는 별도
# 신청/인증키를 쓰는 4개 엔드포인트라 각각 병렬 호출 후 합친다.
_TRAINING_ENDPOINTS: list[tuple[str, str, str]] = [
    ("국민내일배움카드", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do", "worknet_tomorrow_learning_card_api_key"),
    ("사업주훈련", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo311L01.do", "worknet_employer_training_api_key"),
    ("국가인적자원개발컨소시엄", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo312L01.do", "worknet_consortium_training_api_key"),
    ("일학습병행", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo313L01.do", "worknet_work_study_training_api_key"),
]


async def _search_one_training_endpoint(
    label: str,
    url: str,
    api_key: str,
    today: date,
    region: RegionFilter | None = None,
    keyword: str | None = None,
) -> list[JobInfoResult]:
    # 권역 질문은 광역으로 넓게 받아 주소로 걸러내므로 더 많이 받아온다 —
    # 기본 10건만 받으면 경기 첫 10건이 전부 남부일 때 북부 결과가 0건이 된다.
    page_size = _TRAINING_GROUP_PAGE_SIZE if region is not None and region.needs_address_filter else _TRAINING_PER_ENDPOINT_LIMIT
    params = {
        "authKey": api_key,
        "returnType": "XML",
        "outType": "1",
        "pageNum": "1",
        "pageSize": str(page_size),
        "srchTraStDt": today.strftime("%Y%m%d"),
        "srchTraEndDt": (today + timedelta(days=_TRAINING_WINDOW_DAYS)).strftime("%Y%m%d"),
        "sort": "ASC",
        "sortCol": "2",
    }
    if region is not None:
        params.update(region.as_params())
    if keyword:
        params["srchTraProcessNm"] = keyword

    root = await _get(url, params, f"training_course:{label}")
    return [
        result
        for item in root.findall(".//scn_list")
        if (result := _parse_training_item(item, label, region)) is not None
    ]


def _parse_training_item(item: ET.Element, label: str, region: RegionFilter | None) -> JobInfoResult | None:
    """훈련과정 한 건.

    예전엔 `subTitle`을 제목으로 썼는데 그건 **훈련기관 이름**이다("한국폴리텍대학
    춘천캠퍼스"). 과정명은 `title`에 따로 온다(2026-09-11, 4개 엔드포인트 실응답으로
    확인). 링크도 `subTitleLink`는 기관 소개 페이지, `titleLink`가 과정 상세다.
    """
    address = _text(item, "address")
    if region is not None and not region.matches_address(address):
        return None
    institution = _text(item, "subTitle")
    # 일학습병행 과정명은 "2026년_(표준형)재직자_품질경영_L3_…"처럼 밑줄로 이어져 온다.
    course = " ".join(_text(item, "title").replace("_", " ").split()) or institution
    start, end = _text(item, "traStartDate"), _text(item, "traEndDate")
    fee = _text(item, "courseMan")
    meta = [
        m
        for m in (
            f"유형: {label}",
            f"기간: {start} ~ {end}" if start or end else "",
            f"지역: {address}" if address else "",
            f"훈련비: {int(fee):,}원" if fee.isdigit() and int(fee) > 0 else "",
        )
        if m
    ]
    # 과정 id + 회차가 한 개설 과정을 가리킨다 — 해시 대신 안정적인 중복 제거 키.
    course_id, degree = _text(item, "trprId"), _text(item, "trprDegr")
    return JobInfoResult(
        title=course,
        subtitle=institution if institution != course else label,
        meta_lines=meta,
        detail_url=_text(item, "titleLink") or _text(item, "subTitleLink") or None,
        source_key=f"{course_id}:{degree}" if course_id else None,
        region_code=_text(item, "trngAreaCd") or None,
    )


def _training_combos(params: JobInfoQueryParams | None) -> list[tuple[RegionFilter | None, str | None]]:
    """(지역, 키워드) 조합 목록 — 조합 하나가 엔드포인트 4개 호출이 된다.

    같은 파라미터에 값을 여러 개 넣는 건 API가 지원하지 않으므로(콤마는 0건,
    반복은 첫 값만) 값마다 호출을 쪼갠다. 다만 지역×키워드 곱집합을 그대로
    두면 호출이 폭발하니 상한을 둔다.
    """
    if params is None:
        return [(None, None)]

    regions = resolve_region_filters(params.regions, limit=_MAX_REGION_FILTERS) or [None]
    keywords: list[str | None] = list(params.keywords[:_MAX_KEYWORDS]) or [None]

    combos = [(region, keyword) for region in regions for keyword in keywords]
    return combos[:_MAX_TRAINING_COMBOS]


async def search_training_courses(params: JobInfoQueryParams | None = None) -> list[JobInfoResult]:
    # 4개 엔드포인트를 합친 뒤 다시 [:limit]로 자르면 항상 같은 순서로 gather
    # 하는 탓에 뒤쪽 엔드포인트(컨소시엄/일학습병행)의 결과가 매번 통째로
    # 잘려나간다(실사용 라이브 확인으로 발견) — 대신 엔드포인트마다
    # `_TRAINING_PER_ENDPOINT_LIMIT`으로 이미 개별적으로 상한을 두므로, 합친
    # 뒤에는 추가로 자르지 않아 4개 전부 골고루 후보에 들어가게 한다.
    today = date.today()

    async def _safe(
        label: str, url: str, key_field: str, region: RegionFilter | None, keyword: str | None
    ) -> tuple[list[JobInfoResult], bool]:
        """두 번째 값은 이 호출이 실제로 성공했는지다.

        2026-09-12까지는 실패도 성공도 똑같이 `[]`로 뭉개졌다 — "이 조건엔 과정이
        없다"와 "고용24가 오류를 냈다"(그날의 전면 점검 장애 등)가 화면에서
        구분되지 않았다. `_get`/`_check_error`가 이미 로깅하므로 여기서는
        성공 여부만 들고 올라간다.
        """
        api_key = getattr(settings, key_field)
        try:
            return await _search_one_training_endpoint(label, url, api_key, today, region, keyword), True
        except WorknetApiError:
            return [], False

    async def _run(combos: list[tuple[RegionFilter | None, str | None]]) -> tuple[list[JobInfoResult], bool]:
        outcomes = await asyncio.gather(
            *[
                _safe(label, url, key_field, region, keyword)
                for region, keyword in combos
                for label, url, key_field in _TRAINING_ENDPOINTS
            ]
        )
        any_ok = any(ok for _, ok in outcomes)
        # 조합을 여러 개 던지면 같은 과정이 중복으로 들어온다.
        merged: list[JobInfoResult] = []
        seen: set[tuple] = set()
        for group, _ in outcomes:
            for r in group:
                # 부제가 이제 훈련기관명이라 유형(meta 첫 줄)까지 넣어야 서로 다른
                # 엔드포인트의 과정이 합쳐지지 않는다. 같은 엔드포인트를 다른 지역
                # 조합으로 부른 중복은 meta까지 같으므로 여전히 합쳐진다.
                key = (r.title, r.subtitle, tuple(r.meta_lines))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(r)
        return merged, any_ok

    def _results_or_raise(results: list[JobInfoResult], any_ok: bool) -> list[JobInfoResult]:
        if not any_ok:
            # 이번에 시도한 조합의 엔드포인트가 전부 실패했다 — 다른 5개
            # 카테고리처럼 job_search.py가 skipped_category_labels로 분류하게
            # 다시 던진다. 성공한 호출이 하나라도 있었으면(0건 포함) 여기 안 온다.
            raise WorknetApiError("training_course", "all endpoints failed")
        return results

    combos = _training_combos(params)
    if combos == [(None, None)]:
        results, any_ok = await _run(combos)
        return _results_or_raise(results, any_ok)

    results, any_ok = await _run(combos)
    if len(results) >= _MIN_RESULTS_BEFORE_WIDENING:
        return _results_or_raise(results, any_ok)

    # 조건이 너무 좁으면 단계적으로 넓힌다. 실측(devlog 20): "경기 북부 +
    # 자바/웹 개발"은 2건만 남았는데, 지역만으로 조회하면 경기 북부 과정이
    # 4건이었다 — 과정명에 그 키워드가 안 들어간 IT 과정이 통째로 빠진 것이다.
    # 지역은 사용자가 명시한 조건이라 유지하고 키워드만 떼는 것이 순서상 맞다.
    regions = resolve_region_filters(params.regions, limit=_MAX_REGION_FILTERS) if params else []
    if regions:
        widened, widened_ok = await _run([(region, None) for region in regions])
        any_ok = any_ok or widened_ok
        merged = {(r.title, r.subtitle): r for r in [*results, *widened]}
        if merged:
            return _results_or_raise(list(merged.values()), any_ok)

    # 그래도 0건이면 조건을 다 뗀다. 고용24은 유효하지 않은 코드에도 에러가
    # 아니라 빈 목록을 주기 때문에(실측: 광주 29는 두 엔드포인트 모두 0건)
    # "코드가 틀렸다"와 "그 지역에 과정이 없다"를 구분할 수 없다 — 조용히 빈
    # 화면을 주는 것보다 넓은 결과를 주고 관련성 판단에 맡기는 쪽이 낫다.
    final, final_ok = await _run([(None, None)])
    return _results_or_raise(final, any_ok or final_ok)


CATEGORY_SEARCH_FUNCTIONS = {
    "job_fair": search_job_fairs,
    "public_recruitment": search_public_recruitment,
    "public_recruitment_company": search_public_recruitment_companies,
    "training_course": search_training_courses,
    "job_seeker_program": search_job_seeker_programs,
    "promising_sme": search_promising_smes,
}

CATEGORY_LABELS = {
    "job_fair": "채용행사",
    "public_recruitment": "공채속보",
    "public_recruitment_company": "공채기업정보",
    "training_course": "직업훈련과정",
    "job_seeker_program": "구직자취업역량 강화프로그램",
    "promising_sme": "강소기업",
}


class JobInfoClient:
    """카테고리 검색 함수들을 한데 묶는 얇은 래퍼 — FastAPI DI로 라우트에
    주입돼서 테스트가 가짜 구현으로 오버라이드할 수 있게 한다(get_llm_provider/
    get_storage와 같은 패턴). 여기서 돌려주는 건 고용24 원본 목록 그대로다 —
    실제 사용자 질문과 관련 있는 항목만 고르는 건 LLM의
    select_relevant_job_info_results가 한다(app/api/job_search.py)."""

    async def search(
        self, category: str, params: JobInfoQueryParams | None = None, limit: int | None = None
    ) -> list[JobInfoResult]:
        """limit은 job_search.py의 "결과가 모자라면 더 넓게 다시 조회한다" 재시도
        전용(devlog 44) — 평소 호출은 안 넘겨 각 검색 함수의 기본값을 그대로 쓴다."""
        func = CATEGORY_SEARCH_FUNCTIONS[category]
        if category in _FILTERABLE_CATEGORIES:
            return await func(params, limit) if limit else await func(params)
        return await func(limit) if limit else await func()


def get_job_info_client() -> JobInfoClient:
    return JobInfoClient()
