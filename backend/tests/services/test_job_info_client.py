from __future__ import annotations

import httpx
import pytest

from app.services.job_pipeline import job_info_client as jic
from app.services.job_pipeline.job_info_client import JobInfoResult, WorknetApiError
from app.services.llm.base import JobInfoQueryParams

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


# --- 조회 조건을 실어 보내는 경로 (devlog 20) ---
#
# 예전에는 조건을 넘길 수단이 없어 전국 첫 20건을 무조건 받아왔다. 그래서
# "경기 북부 백엔드"라고 물어도 후보에 강원/경남 과정이 들어오니 관련성
# 판단이 아무리 정확해도 건질 게 없었다.


def test_no_params_means_one_unfiltered_combo():
    assert jic._training_combos(None) == [(None, None)]
    assert jic._training_combos(JobInfoQueryParams()) == [(None, None)]


def test_each_same_dimension_value_becomes_its_own_combo():
    # 같은 파라미터에 값을 여러 개 넣는 건 API가 지원하지 않는다 — 콤마는 0건,
    # 반복 파라미터는 첫 값만 적용된다(실측).
    combos = jic._training_combos(JobInfoQueryParams(regions=["서울", "부산"], keywords=["자바"]))

    assert [(r.area1, k) for r, k in combos] == [("11", "자바"), ("26", "자바")]


def test_keywords_without_a_region_still_produce_one_combo_each():
    combos = jic._training_combos(JobInfoQueryParams(keywords=["자바", "디자인"]))

    assert [(r, k) for r, k in combos] == [(None, "자바"), (None, "디자인")]


def test_combo_count_is_capped():
    # 조합 하나가 엔드포인트 4개 호출이 되므로 상한이 없으면 호출이 폭발한다.
    combos = jic._training_combos(JobInfoQueryParams(regions=["서울", "부산", "대구"], keywords=["자바", "디자인"]))

    assert len(combos) <= jic._MAX_TRAINING_COMBOS


@pytest.mark.asyncio
async def test_filters_are_passed_through_to_every_endpoint(monkeypatch):
    calls: list[tuple] = []

    async def fake_endpoint(label, url, api_key, today, region=None, keyword=None):
        calls.append((label, region.area1 if region else None, keyword))
        # 확대 임계값을 넘길 만큼 돌려줘서 이 테스트가 통과 경로만 보게 한다.
        return [JobInfoResult(title=f"{label} 과정 {i}", subtitle=label, meta_lines=[]) for i in range(5)]

    monkeypatch.setattr(jic, "_search_one_training_endpoint", fake_endpoint)

    results = await jic.search_training_courses(JobInfoQueryParams(regions=["경기 북부"], keywords=["자바"]))

    # 엔드포인트 4개 × 조합 1개, 결과가 넉넉하니 확대 없이 끝난다.
    assert len(calls) == 4
    assert {c[1] for c in calls} == {"41"}
    assert {c[2] for c in calls} == {"자바"}
    assert len(results) == 20


@pytest.mark.asyncio
async def test_too_few_results_widens_by_dropping_the_keyword_but_keeps_the_region(monkeypatch):
    # 실측(devlog 20): "경기 북부 + 자바/웹 개발"은 2건이었는데 지역만으로는
    # 4건이었다 — 과정명에 그 키워드가 없는 IT 과정이 통째로 빠진 것이다.
    # 지역은 사용자가 명시한 조건이라 유지하고 키워드만 뗀다.
    calls: list[tuple] = []

    async def fake_endpoint(label, url, api_key, today, region=None, keyword=None):
        calls.append((region.area1 if region else None, keyword))
        if keyword is not None:
            return [JobInfoResult(title="키워드로 찾은 과정", subtitle=label, meta_lines=[])]
        return [JobInfoResult(title=f"지역만으로 찾은 과정 {label}", subtitle=label, meta_lines=[])]

    monkeypatch.setattr(jic, "_search_one_training_endpoint", fake_endpoint)

    results = await jic.search_training_courses(JobInfoQueryParams(regions=["경기 북부"], keywords=["자바"]))

    assert ("41", "자바") in calls, "먼저 키워드까지 걸고 시도해야 한다"
    assert ("41", None) in calls, "결과가 적으면 키워드만 떼고 넓혀야 한다"
    assert (None, None) not in calls, "지역은 사용자가 말한 조건이라 유지해야 한다"
    titles = {r.title for r in results}
    assert "키워드로 찾은 과정" in titles
    assert any(t.startswith("지역만으로 찾은 과정") for t in titles)


@pytest.mark.asyncio
async def test_duplicate_courses_across_combos_are_merged(monkeypatch):
    async def fake_endpoint(label, url, api_key, today, region=None, keyword=None):
        # 조합이 달라도 같은 과정이 걸려 나오는 상황.
        return [JobInfoResult(title="같은 과정", subtitle="국민내일배움카드 · 고양", meta_lines=[])]

    monkeypatch.setattr(jic, "_search_one_training_endpoint", fake_endpoint)

    results = await jic.search_training_courses(JobInfoQueryParams(regions=["서울", "부산"]))

    assert len(results) == 1


@pytest.mark.asyncio
async def test_zero_filtered_results_falls_back_to_an_unfiltered_fetch(monkeypatch):
    # 워크넷은 유효하지 않은 코드에도 에러가 아니라 빈 목록을 준다(실측: 광주
    # 29는 두 엔드포인트 모두 0건) — "코드가 틀렸다"와 "그 지역에 과정이 없다"를
    # 구분할 수 없으니, 조용히 빈 화면을 주는 대신 넓혀서 다시 받아온다.
    attempts: list[tuple] = []

    async def fake_endpoint(label, url, api_key, today, region=None, keyword=None):
        attempts.append((region.area1 if region else None, keyword))
        if region is not None or keyword is not None:
            return []
        return [JobInfoResult(title="조건 없이 찾은 과정", subtitle=label, meta_lines=[])]

    monkeypatch.setattr(jic, "_search_one_training_endpoint", fake_endpoint)

    results = await jic.search_training_courses(JobInfoQueryParams(regions=["광주"], keywords=["자바"]))

    assert [a for a in attempts if a != (None, None)], "먼저 조건을 걸고 시도해야 한다"
    assert (None, None) in attempts, "그래도 0건이면 조건을 다 떼고 재시도해야 한다"
    assert len(results) == 4
    assert results[0].title == "조건 없이 찾은 과정"


@pytest.mark.asyncio
async def test_unfiltered_search_does_not_retry(monkeypatch):
    # 애초에 조건이 없었으면 재시도할 게 없다 — 같은 호출을 두 번 하지 않는다.
    attempts: list[tuple] = []

    async def fake_endpoint(label, url, api_key, today, region=None, keyword=None):
        attempts.append((region, keyword))
        return []

    monkeypatch.setattr(jic, "_search_one_training_endpoint", fake_endpoint)

    results = await jic.search_training_courses(None)

    assert results == []
    assert len(attempts) == 4  # 엔드포인트 4개, 재시도 없음
