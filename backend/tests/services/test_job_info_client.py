from __future__ import annotations

import httpx
import pytest

from app.services.job_pipeline import job_info_client as jic
from app.services.job_pipeline.job_info_client import WorknetApiError

# 실제로 관찰된 오류 응답 두 형태(2026-09-08) — 정상 응답과 구분하려면 둘 다
# 정확히 잡아내야 한다.
_ERROR_XML_WANTED_ROOT = '<?xml version="1.0" encoding="UTF-8"?><wantedRoot><message>유효하지 않은 인증키 입니다.</message><messageCd>002</messageCd></wantedRoot>'
_ERROR_XML_GO24 = "<?xml version='1.0' encoding='UTF-8'?><GO24><error>개인회원은 사용할 수 없는 OPEN-API입니다.</error></GO24>"

_JOB_FAIR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<empEvList><total>1</total><empEvent>
  <areaCd>56</areaCd><area>대전/충청 지역</area><eventNo>49160</eventNo>
  <eventNm>2026년 충청권 취업박람회</eventNm><eventTerm>2026-10-16 ~ 2026-10-16</eventTerm>
</empEvent></empEvList>
"""

_PUBLIC_RECRUITMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<dhsOpenEmpInfoList><total>1</total><dhsOpenEmpInfo>
  <empSeqno>177320</empSeqno><empWantedTitle>2026년 신규직원 채용</empWantedTitle>
  <empBusiNm>농업협동조합중앙회</empBusiNm><coClcdNm>대기업</coClcdNm>
  <empWantedStdt>20260907</empWantedStdt><empWantedEndt>20260917</empWantedEndt>
  <empWantedTypeNm>정규직</empWantedTypeNm>
  <empWantedHomepgDetail>https://nhcenter.incruit.com/hire/1</empWantedHomepgDetail>
</dhsOpenEmpInfo></dhsOpenEmpInfoList>
"""

_PUBLIC_RECRUITMENT_COMPANY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<dhsOpenEmpHireInfoList><total>1</total><dhsOpenEmpHireInfo>
  <coClcdNm>중견기업</coClcdNm><coNm>한독헬스케어</coNm>
  <coIntroSummaryCont>안전성과 효능이 검증된 헬스케어 솔루션을 제공하는 전문 기업</coIntroSummaryCont>
</dhsOpenEmpHireInfo></dhsOpenEmpHireInfoList>
"""

_JOB_SEEKER_PROGRAM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<empPgmSchdInviteList><total>1</total><empPgmSchdInvite>
  <orgNm>구미고용센터</orgNm><pgmNm>성취</pgmNm>
  <pgmSubNm>구직자 취업 자신감 향상, 이력서 작성 및 면접 향상</pgmSubNm>
  <pgmStdt>20260908</pgmStdt><pgmEndt>20260911</pgmEndt>
  <openPlcCont>구미고용센터 5층 프로그램실</openPlcCont>
</empPgmSchdInvite></empPgmSchdInviteList>
"""

_PROMISING_SME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<smallGiantsList><total>1</total><smallGiant>
  <coNm>주식회사 케이피에프</coNm><indTpNm>금속가공제품 제조업</indTpNm>
  <regionNm>충북 충주시</regionNm><coMainProd>볼트,너트,차량용단조품</coMainProd>
</smallGiant></smallGiantsList>
"""

_TRAINING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HRDNet><pageNum>1</pageNum><scn_cnt>1</scn_cnt><srchList><scn_list>
  <address>서울 구로구</address><subTitle>(주)휴넷</subTitle>
  <subTitleLink>https://www.work24.go.kr/hr/course/1</subTitleLink>
</scn_list></srchList></HRDNet>
"""


def _mock_get(monkeypatch, xml_text: str):
    async def fake_get(self, url, params=None, **kwargs):
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, text=xml_text, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.mark.asyncio
async def test_search_job_fairs_parses_real_shaped_response(monkeypatch):
    _mock_get(monkeypatch, _JOB_FAIR_XML)
    results = await jic.search_job_fairs()
    assert len(results) == 1
    assert results[0].title == "2026년 충청권 취업박람회"
    assert results[0].subtitle == "대전/충청 지역"
    assert results[0].meta_lines == ["기간: 2026-10-16 ~ 2026-10-16"]


@pytest.mark.asyncio
async def test_search_public_recruitment_parses_real_shaped_response(monkeypatch):
    _mock_get(monkeypatch, _PUBLIC_RECRUITMENT_XML)
    results = await jic.search_public_recruitment()
    assert results[0].title == "2026년 신규직원 채용"
    assert results[0].subtitle == "농업협동조합중앙회"
    assert results[0].detail_url == "https://nhcenter.incruit.com/hire/1"
    assert "규모: 대기업" in results[0].meta_lines


@pytest.mark.asyncio
async def test_search_public_recruitment_companies_parses_real_shaped_response(monkeypatch):
    _mock_get(monkeypatch, _PUBLIC_RECRUITMENT_COMPANY_XML)
    results = await jic.search_public_recruitment_companies()
    assert results[0].title == "한독헬스케어"
    assert "헬스케어" in results[0].meta_lines[-1]


@pytest.mark.asyncio
async def test_search_job_seeker_programs_parses_real_shaped_response(monkeypatch):
    _mock_get(monkeypatch, _JOB_SEEKER_PROGRAM_XML)
    results = await jic.search_job_seeker_programs()
    assert results[0].title == "성취"
    assert any("구미고용센터" in m for m in results[0].meta_lines)


@pytest.mark.asyncio
async def test_search_promising_smes_parses_real_shaped_response(monkeypatch):
    _mock_get(monkeypatch, _PROMISING_SME_XML)
    results = await jic.search_promising_smes()
    assert results[0].title == "주식회사 케이피에프"
    assert "업종: 금속가공제품 제조업" in results[0].meta_lines


@pytest.mark.asyncio
async def test_get_raises_worknet_api_error_on_wanted_root_error_envelope(monkeypatch):
    _mock_get(monkeypatch, _ERROR_XML_WANTED_ROOT)
    with pytest.raises(WorknetApiError) as exc_info:
        await jic.search_job_fairs()
    assert "인증키" in exc_info.value.message


@pytest.mark.asyncio
async def test_get_raises_worknet_api_error_on_go24_error_envelope(monkeypatch):
    _mock_get(monkeypatch, _ERROR_XML_GO24)
    with pytest.raises(WorknetApiError) as exc_info:
        await jic.search_promising_smes()
    assert "개인회원" in exc_info.value.message


@pytest.mark.asyncio
async def test_search_training_courses_aggregates_all_four_endpoints(monkeypatch):
    _mock_get(monkeypatch, _TRAINING_XML)
    results = await jic.search_training_courses()
    # 4개 엔드포인트가 전부 같은 mock을 쓰므로 항목당 1건씩 총 4건이 합쳐진다.
    assert len(results) == 4
    assert all(r.title == "(주)휴넷" for r in results)


@pytest.mark.asyncio
async def test_search_training_courses_continues_when_one_endpoint_fails(monkeypatch):
    calls = {"n": 0}

    async def fake_get(self, url, params=None, **kwargs):
        calls["n"] += 1
        # 첫 호출만 오류로 응답 — 나머지 3개는 정상.
        xml = _ERROR_XML_GO24 if calls["n"] == 1 else _TRAINING_XML
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, text=xml, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    results = await jic.search_training_courses()
    assert len(results) == 3
