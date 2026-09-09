from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services.feed.sources import configured_sources
from app.services.feed.sources.youthcenter_source import (
    YouthCenterApiError,
    YouthCenterFeedSource,
)

# 2026-09-09 실 인증키로 받은 **진짜 응답**을 그대로 붙여넣은 것이다
# (pageSize=2). 이전 버전은 문서에서 유추한 XML을 넣고 xfail로 달아뒀는데,
# 실제로는 응답이 JSON이었고 엔드포인트도 달랐다 — 유추한 픽스처는 통과해도
# 아무것도 보증하지 못한다는 걸 그대로 보여준 사례다.
_REAL_POLICY_JSON = {
  "resultCode": 200,
  "resultMessage": "성공적으로 데이터를 가지고 왔습니다.",
  "result": {
    "pagging": {
      "totCount": 2751,
      "pageNum": 1,
      "pageSize": 2
    },
    "youthPolicyList": [
      {
        "plcyNo": "20260908005400213380",
        "bscPlanCycl": "2",
        "bscPlanPlcyWayNo": "002",
        "bscPlanFcsAsmtNo": "005",
        "bscPlanAsmtNo": "019",
        "pvsnInstGroupCd": "0054002",
        "plcyPvsnMthdCd": "0042002",
        "plcyAprvSttsCd": "0044002",
        "plcyNm": "경기도 대학혁신플랫폼 지원",
        "plcyKywdNm": "교육지원",
        "plcyExplnCn": "○ (사업목적) 우수 역량과 인프라를 보유한 대학을 중심으로, 반도체와 바이오헬스 분야에 대해 기업 수요 맞춤형 실무 인력양성 및 기술협력 지원\n○ ('26년 사업비) 1,050백만원(도비)  \n○ (수행기관) 가천대혁신플랫폼(바이오헬스 분야), 성균관대혁신플랫폼(반도체 분야)",
        "lclsfNm": "교육･직업훈련",
        "mclsfNm": "미래역량강화",
        "plcySprtCn": "○ 반도체, 바이오헬스 분야에 대한 수준별 교육 및 현장실습으로 수요 맞춤형･실무형 인력 양성과 교육 수료자 취업 연계\n○ 공정개선, 기술자문 및 인증지원, 장비활용 등 현장 밀착형 기업 협력ㆍ지원",
        "sprvsnInstCd": "6410000",
        "sprvsnInstCdNm": "경기도",
        "sprvsnInstPicNm": "서영섭",
        "operInstCd": "7008143",
        "operInstCdNm": "가천대학교",
        "operInstPicNm": "",
        "sprtSclLmtYn": "Y",
        "aplyPrdSeCd": "0057002",
        "bizPrdSeCd": "0056001",
        "bizPrdBgngYmd": "20260101",
        "bizPrdEndYmd": "20270228",
        "bizPrdEtcCn": "",
        "plcyAplyMthdCn": "각 대학혁신플랫폼(가천대, 성균관대) 문의 또는 통합 홈페이지(http://grrc.koreasarang.co.kr)를 통해 신청",
        "srngMthdCn": "개별 통보",
        "aplyUrlAddr": "http://grrc.koreasarang.co.kr",
        "sbmsnDcmntCn": "",
        "etcMttrCn": "",
        "refUrlAddr1": "http://grrc.koreasarang.co.kr",
        "refUrlAddr2": "",
        "sprtSclCnt": "0",
        "sprtArvlSeqYn": "N",
        "sprtTrgtMinAge": "0",
        "sprtTrgtMaxAge": "0",
        "sprtTrgtAgeLmtYn": "Y",
        "mrgSttsCd": "0055003",
        "earnCndSeCd": "0043001",
        "earnMinAmt": "0",
        "earnMaxAmt": "0",
        "earnEtcCn": "",
        "addAplyQlfcCndCn": "",
        "ptcpPrpTrgtCn": "",
        "inqCnt": "30",
        "rgtrInstCd": "6410000",
        "rgtrInstCdNm": "경기도",
        "rgtrUpInstCd": "0000000",
        "rgtrUpInstCdNm": "경기도",
        "rgtrHghrkInstCd": "6410000",
        "rgtrHghrkInstCdNm": "경기도",
        "zipCd": "41111,41113,41115,41117,41131,41133,41135,41150,41171,41173,41192,41194,41196,41210,41220,41250,41271,41273,41281,41285,41287,41290,41310,41360,41370,41390,41410,41430,41450,41461,41463,41465,41480,41500,41550,41570,41591,41593,41595,41597,41610,41630,41650,41670,41800,41820,41830",
        "plcyMajorCd": "0011009",
        "jobCd": "0013001,0013003,0013006",
        "schoolCd": "0049010",
        "aplyYmd": "",
        "frstRegDt": "2026-09-08 09:13:11",
        "lastMdfcnDt": "2026-09-08 09:20:19",
        "sbizCd": "0014001,0014008"
      },
      {
        "plcyNo": "20260907005400213378",
        "bscPlanCycl": "2",
        "bscPlanPlcyWayNo": "001",
        "bscPlanFcsAsmtNo": "002",
        "bscPlanAsmtNo": "004",
        "pvsnInstGroupCd": "0054002",
        "plcyPvsnMthdCd": "0042004",
        "plcyAprvSttsCd": "0044002",
        "plcyNm": "경기도 청년 복지포인트",
        "plcyKywdNm": "중소기업",
        "plcyExplnCn": "경기도 소재 중소·중견기업 등 재직, 경기도 거주 청년에게 복리후생을 지원하여 장기근속 유도",
        "lclsfNm": "일자리",
        "mclsfNm": "취업",
        "plcySprtCn": "경기도 소재 중소·중견기업 등* 재직, 경기도 거주 청년**에게 1년간 120만원 복지포인트 지원\n * 도 소재 중견기업, 중소기업, 소상공인업체, 비영리법인(공기관 등 제외) 재직자\n ** 급여 385만원(기준 중위소득 150%) 이하 재직자 / 주 36시간 이상 6개월 이상 근로자",
        "sprvsnInstCd": "6412843",
        "sprvsnInstCdNm": "경기도 미래평생교육국 청년기회과",
        "sprvsnInstPicNm": "",
        "operInstCd": "       ",
        "operInstCdNm": "",
        "operInstPicNm": "",
        "sprtSclLmtYn": "N",
        "aplyPrdSeCd": "0057001",
        "bizPrdSeCd": "0056001",
        "bizPrdBgngYmd": "20260101",
        "bizPrdEndYmd": "20261231",
        "bizPrdEtcCn": "",
        "plcyAplyMthdCn": "청년 노동자 지원사업 홈페이지(https://youth.jobaba.net/) 온라인 신청",
        "srngMthdCn": "청년 노동자 지원사업 홈페이지(https://youth.jobaba.net/) 선정 결과 발표\n - 접수시작일 직전 6개월 평균 건강보험료가 낮은 순으로 선발",
        "aplyUrlAddr": "https://youth.jobaba.net/",
        "sbmsnDcmntCn": "사업참여신청서, 개인정보제공동의서, 근무확인서, 주민등록초본, 4대 사회보험 가입자 가입내역확인서 등\n\n※ 자세한 사항은 청년 노동자 지원사업 홈페이지(https://youth.jobaba.net/) 참고",
        "etcMttrCn": "",
        "refUrlAddr1": "https://youth.jobaba.net/",
        "refUrlAddr2": "",
        "sprtSclCnt": "0",
        "sprtArvlSeqYn": "N",
        "sprtTrgtMinAge": "19",
        "sprtTrgtMaxAge": "39",
        "sprtTrgtAgeLmtYn": "N",
        "mrgSttsCd": "0055003",
        "earnCndSeCd": "0043003",
        "earnMinAmt": "0",
        "earnMaxAmt": "0",
        "earnEtcCn": "접수시작일 직전 6개월 평균 월급여 385만원 이하",
        "addAplyQlfcCndCn": "- 경기도 내 중소‧중견기업,소상공인업체,비영리법인 재직자(주36시간 이상 근무)\n ※ 자세한 사항은 청년 노동자 지원사업 홈페이지(https://youth.jobaba.net/) 참고",
        "ptcpPrpTrgtCn": "국가근로장학생 / 해외파견자 / 휴직자 / 병역 복무 이행자\n ※ 자세한 사항은 청년 노동자 지원사업 홈페이지(https://youth.jobaba.net/) 참고",
        "inqCnt": "56",
        "rgtrInstCd": "6412843",
        "rgtrInstCdNm": "경기도 미래평생교육국 청년기회과",
        "rgtrUpInstCd": "6412831",
        "rgtrUpInstCdNm": "경기도 미래평생교육국",
        "rgtrHghrkInstCd": "6410000",
        "rgtrHghrkInstCdNm": "경기도",
        "zipCd": "41111,41113,41115,41117,41131,41133,41135,41150,41171,41173,41192,41194,41196,41210,41220,41250,41271,41273,41281,41285,41287,41290,41310,41360,41370,41390,41410,41430,41450,41461,41463,41465,41480,41500,41550,41570,41591,41593,41595,41597,41610,41630,41650,41670,41800,41820,41830",
        "plcyMajorCd": "0011009",
        "jobCd": "0013001",
        "schoolCd": "0049010",
        "aplyYmd": "20260701 ~ 20260713",
        "frstRegDt": "2026-09-07 17:52:20",
        "lastMdfcnDt": "2026-09-08 09:19:37",
        "sbizCd": "0014001"
      }
    ]
  }
}

_ERROR_JSON = {
    "resultCode": 401,
    "resultMessage": "인증키가 유효하지 않습니다.",
    "result": None,
}


def _mock_get(monkeypatch, payload, status_code: int = 200):
    async def fake_get(self, url, params=None, **kwargs):
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(status_code, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


def test_source_is_not_configured_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "youthcenter_api_key", "")
    assert YouthCenterFeedSource().is_configured() is False


def test_unconfigured_source_is_silently_dropped_from_the_registry(monkeypatch):
    """키 미발급은 오류가 아니라 설정 상태다 — 예외를 던지면 승인될 때까지
    메인 화면에 빨간 배너가 계속 뜬다."""
    monkeypatch.setattr(settings, "youthcenter_api_key", "")
    names = [s.name for s in configured_sources()]
    assert "youthcenter" not in names
    assert "worknet" in names  # 나머지 소스는 그대로 살아 있어야 한다


@pytest.mark.asyncio
async def test_parses_the_real_response(monkeypatch):
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    _mock_get(monkeypatch, _REAL_POLICY_JSON)

    results = await YouthCenterFeedSource().fetch("youth_policy")

    assert len(results) == 2
    item = results[0]
    assert item.title == '경기도 대학혁신플랫폼 지원'
    assert item.source == "youthcenter"
    assert item.category == "youth_policy"
    assert item.feed_kind == "policy"          # 정책 탭으로 간다
    assert item.subtitle == '경기도'                 # 주관기관
    assert item.source_key == '20260908005400213380'               # plcyNo — 안정적인 중복 제거 키
    assert item.detail_url is not None
    assert item.source_published_at is not None
    # 분류를 첫 줄에 실어 카드에서 바로 구분되게 한다(분류로 걸러내지 않으므로).
    assert item.meta_lines[0].startswith("분류: ")


@pytest.mark.asyncio
async def test_reg_date_is_parsed_from_a_datetime_string(monkeypatch):
    """frstRegDt는 "2026-09-08 09:13:11" 형태다 — 다른 소스처럼 YYYYMMDD가 아니다."""
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    _mock_get(monkeypatch, _REAL_POLICY_JSON)

    item = (await YouthCenterFeedSource().fetch("youth_policy"))[0]
    assert item.source_published_at.isoformat() == '2026-09-08'


@pytest.mark.asyncio
async def test_error_body_with_http_200_raises(monkeypatch):
    """이 API는 실패해도 HTTP 200으로 오고 본문 resultCode로만 구분된다 —
    raise_for_status로는 못 잡는다(워크넷과 같은 계열의 함정)."""
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    _mock_get(monkeypatch, _ERROR_JSON)

    with pytest.raises(YouthCenterApiError):
        await YouthCenterFeedSource().fetch("youth_policy")


@pytest.mark.asyncio
async def test_items_without_a_title_are_skipped(monkeypatch):
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    _mock_get(monkeypatch, {"resultCode": 200, "result": {"youthPolicyList": [{"plcyNo": "x", "plcyNm": ""}]}})

    assert await YouthCenterFeedSource().fetch("youth_policy") == []


@pytest.mark.asyncio
async def test_empty_list_is_not_an_error(monkeypatch):
    monkeypatch.setattr(settings, "youthcenter_api_key", "some-key")
    _mock_get(monkeypatch, {"resultCode": 200, "result": {"youthPolicyList": []}})

    assert await YouthCenterFeedSource().fetch("youth_policy") == []
