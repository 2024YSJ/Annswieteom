from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from app.core.config import settings

# 훈련과정 조회는 날짜 범위가 필수인데(공식 명세) 사용자 질문에서 날짜를
# 뽑아내는 건 이번 범위 밖이라(devlog 16 계획 참고) 항상 "오늘부터 90일"로
# 고정한다 — 곧 시작하는/모집 중인 과정 위주로 보여주는 셈이라 실용적인 기본값.
_TRAINING_WINDOW_DAYS = 90

# 카테고리당 워크넷에서 받아오는 원본 건수 상한 — 이 목록 전체가 그대로
# select_relevant_job_info_results 프롬프트에 들어가므로(devlog 18: 문자열
# 부분일치 대신 LLM이 실제로 관련 있는 항목을 골라내는 방식으로 교체), 로컬
# LLM 호출 하나에 무리 없이 들어갈 만큼만 가져온다.
_FETCH_LIMIT = 20
_TRAINING_PER_ENDPOINT_LIMIT = 10


class WorknetApiError(Exception):
    """워크넷/고용24가 정상 목록 대신 오류 응답을 돌려준 경우(인증키 미승인,
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


@dataclass
class JobInfoResult:
    """6개 카테고리 전부가 공유하는 결과 모양 — 각 워크넷 API의 XML 필드가
    전부 다르므로(카테고리별 파서 참고) 프론트가 카테고리 상관없이 카드 하나로
    그릴 수 있게 여기서 정규화한다."""
    title: str
    subtitle: str
    meta_lines: list[str]
    detail_url: str | None = None


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
        raise WorknetApiError(category, error_text_el.text.strip() if error_text_el.text else None)


async def _get(url: str, params: dict[str, str], category: str) -> ET.Element:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        _check_error(root, category)
        return root


async def search_job_fairs(limit: int = _FETCH_LIMIT) -> list[JobInfoResult]:
    root = await _get(
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L11.do",
        {"authKey": settings.worknet_job_posting_api_key, "returnType": "XML", "callTp": "L", "startPage": "1", "display": str(limit)},
        "job_fair",
    )
    results = []
    for item in root.findall(".//empEvent"):
        term = _text(item, "eventTerm")
        results.append(
            JobInfoResult(title=_text(item, "eventNm"), subtitle=_text(item, "area"), meta_lines=[f"기간: {term}"] if term else [])
        )
    return results


async def search_public_recruitment(limit: int = _FETCH_LIMIT) -> list[JobInfoResult]:
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
                detail_url=_text(item, "empWantedHomepgDetail") or None,
            )
        )
    return results


async def search_public_recruitment_companies(limit: int = _FETCH_LIMIT) -> list[JobInfoResult]:
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
        results.append(JobInfoResult(title=_text(item, "coNm"), subtitle=co_size, meta_lines=meta))
    return results


async def search_job_seeker_programs(limit: int = _FETCH_LIMIT) -> list[JobInfoResult]:
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


async def search_promising_smes(limit: int = _FETCH_LIMIT) -> list[JobInfoResult]:
    root = await _get(
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo216L01.do",
        {"authKey": settings.worknet_promising_sme_api_key, "returnType": "XML", "callTp": "L", "startPage": "1", "display": str(limit)},
        "promising_sme",
    )
    results = []
    for item in root.findall(".//smallGiant"):
        industry = _text(item, "indTpNm")
        region = _text(item, "regionNm")
        product = _text(item, "coMainProd")
        meta = [m for m in [f"업종: {industry}" if industry else "", f"지역: {region}" if region else "", f"주요생산품: {product}" if product else ""] if m]
        results.append(JobInfoResult(title=_text(item, "coNm"), subtitle=industry, meta_lines=meta))
    return results


# 훈련과정 4종 — 사용자에게는 "직업훈련과정" 하나로 보이지만 실제로는 별도
# 신청/인증키를 쓰는 4개 엔드포인트라 각각 병렬 호출 후 합친다.
_TRAINING_ENDPOINTS: list[tuple[str, str, str]] = [
    ("국민내일배움카드", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do", "worknet_tomorrow_learning_card_api_key"),
    ("사업주훈련", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo311L01.do", "worknet_employer_training_api_key"),
    ("국가인적자원개발컨소시엄", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo312L01.do", "worknet_consortium_training_api_key"),
    ("일학습병행", "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo313L01.do", "worknet_work_study_training_api_key"),
]


async def _search_one_training_endpoint(label: str, url: str, api_key: str, today: date) -> list[JobInfoResult]:
    params = {
        "authKey": api_key,
        "returnType": "XML",
        "outType": "1",
        "pageNum": "1",
        "pageSize": str(_TRAINING_PER_ENDPOINT_LIMIT),
        "srchTraStDt": today.strftime("%Y%m%d"),
        "srchTraEndDt": (today + timedelta(days=_TRAINING_WINDOW_DAYS)).strftime("%Y%m%d"),
        "sort": "ASC",
        "sortCol": "2",
    }
    root = await _get(url, params, f"training_course:{label}")
    results = []
    for item in root.findall(".//scn_list"):
        address = _text(item, "address")
        results.append(
            JobInfoResult(
                title=_text(item, "subTitle"),
                subtitle=f"{label} · {address}" if address else label,
                meta_lines=[],
                detail_url=_text(item, "subTitleLink") or None,
            )
        )
    return results


async def search_training_courses() -> list[JobInfoResult]:
    # 4개 엔드포인트를 합친 뒤 다시 [:limit]로 자르면 항상 같은 순서로 gather
    # 하는 탓에 뒤쪽 엔드포인트(컨소시엄/일학습병행)의 결과가 매번 통째로
    # 잘려나간다(실사용 라이브 확인으로 발견) — 대신 엔드포인트마다
    # `_TRAINING_PER_ENDPOINT_LIMIT`으로 이미 개별적으로 상한을 두므로, 합친
    # 뒤에는 추가로 자르지 않아 4개 전부 골고루 후보에 들어가게 한다.
    today = date.today()

    async def _safe(label: str, url: str, key_field: str) -> list[JobInfoResult]:
        api_key = getattr(settings, key_field)
        try:
            return await _search_one_training_endpoint(label, url, api_key, today)
        except WorknetApiError:
            # 훈련과정 4개 중 하나가 실패해도(개별 카테고리 승인 상태가 다를 수
            # 있음) 나머지로 계속 진행한다 — 전부 실패하면 결과가 빈 채로
            # 돌아가고, 라우트가 그걸 그대로 "결과 없음"으로 보여준다.
            return []

    results_per_endpoint = await asyncio.gather(
        *[_safe(label, url, key_field) for label, url, key_field in _TRAINING_ENDPOINTS]
    )
    return [r for group in results_per_endpoint for r in group]


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
    get_storage와 같은 패턴). 여기서 돌려주는 건 워크넷 원본 목록 그대로다 —
    실제 사용자 질문과 관련 있는 항목만 고르는 건 LLM의
    select_relevant_job_info_results가 한다(app/api/job_search.py)."""

    async def search(self, category: str) -> list[JobInfoResult]:
        func = CATEGORY_SEARCH_FUNCTIONS[category]
        return await func()


def get_job_info_client() -> JobInfoClient:
    return JobInfoClient()
