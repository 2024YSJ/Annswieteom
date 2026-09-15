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
  <coClcdNm>중견기업</coClcdNm><coNm>한독헬스케어</coNm><empCoNo>E000026363</empCoNo>
  <busino>4778803393</busino>
  <coIntroSummaryCont>안전성과 효능이 검증된 헬스케어 솔루션을 제공하는 전문 기업</coIntroSummaryCont>
  <homepg>https://handok.recruiter.co.kr/career/company</homepg>
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
  <coNm>주식회사 케이피에프</coNm><indTpNm>금속가공제품 제조업</indTpNm><busiNo>3038515748</busiNo>
  <regionNm>충북 충주시</regionNm><coMainProd>볼트,너트,차량용단조품</coMainProd>
</smallGiant></smallGiantsList>
"""

#: 2026-09-11 국민내일배움카드 실응답에서 쓰는 필드만 옮겼다. subTitle은
#: 훈련기관명, title이 과정명이다 — 예전 파서는 subTitle을 제목으로 썼다.
_TRAINING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HRDNet><pageNum>1</pageNum><scn_cnt>1</scn_cnt><srchList><scn_list>
  <address>전북 전주시 완산구</address><courseMan>880000</courseMan>
  <subTitle>평화요양보호사교육원</subTitle>
  <subTitleLink>https://www.work24.go.kr/hr/a/a/3200/selectTrainInstitution.do?tracseId=AIG20250000524</subTitleLink>
  <title>요양보호사자격취득과정</title>
  <titleLink>https://www.work24.go.kr/hr/a/a/3100/selectTracseDetl.do?tracseId=AIG20250000524</titleLink>
  <traStartDate>2026-09-11</traStartDate><traEndDate>2027-01-10</traEndDate>
  <trprDegr>9</trprDegr><trprId>AIG20250000524076</trprId><trngAreaCd>52111</trngAreaCd>
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
    # 상세 페이지 파라미터 이름이 API 필드명과 다르다(eventNo -> newsDataSeqno,
    # areaCd -> eventMegaRegionCd). 이 조합을 2026-09-10에 실제 행사로 확인했다.
    assert results[0].detail_url == (
        "https://www.work24.go.kr/wk/a/f/1100/retrieveEmpEventDtl.do"
        "?newsDataSeqno=49160&eventMegaRegionCd=56"
    )
    assert results[0].source_key == "49160"


@pytest.mark.asyncio
async def test_job_fair_without_a_region_code_gets_no_link(monkeypatch):
    """지역 코드가 없으면 상세 페이지가 안 열린다 — 그럴 땐 링크를 안 만든다.

    안 열리는 링크는 링크가 없는 것보다 나쁘다(카드가 눌리는 것처럼 보인다).
    """
    _mock_get(
        monkeypatch,
        _JOB_FAIR_XML.replace("<areaCd>56</areaCd>", "<areaCd></areaCd>"),
    )
    results = await jic.search_job_fairs()
    assert results[0].detail_url is None
    assert results[0].source_key == "49160"


@pytest.mark.asyncio
async def test_search_job_fairs_sends_the_keyword_when_params_have_one(monkeypatch):
    """2026-09-13 실측 확인: keyword가 eventNm 부분일치로 반영된다."""
    captured = {}

    async def fake_get(self, url, params=None, **kwargs):
        captured.update(params or {})
        return httpx.Response(200, text=_JOB_FAIR_XML, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await jic.search_job_fairs(JobInfoQueryParams(regions=["경기"], keywords=["간호"]))
    assert captured["keyword"] == "간호"


@pytest.mark.asyncio
async def test_search_job_fairs_sends_no_keyword_when_params_is_none(monkeypatch):
    """worknet_source.py(피드 수집)는 params 없이 limit만 넘긴다 — 공유 캐시가
    한 사용자의 조건으로 좁혀지면 안 된다."""
    captured = {}

    async def fake_get(self, url, params=None, **kwargs):
        captured.update(params or {})
        return httpx.Response(200, text=_JOB_FAIR_XML, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await jic.search_job_fairs(limit=50)
    assert "keyword" not in captured


@pytest.mark.asyncio
async def test_search_job_fairs_expands_a_mapped_keyword_into_multiple_calls(monkeypatch):
    """occupation_synonyms에 있는 직업이면 표현을 여러 개 시도한다(devlog 46) —
    eventNm 리터럴 부분일치라 사용자가 말한 표현이 실제 행사명과 다르면 조용히
    0건이 되기 때문이다."""
    monkeypatch.setattr(jic, "expand_occupation_keyword", lambda kw, limit: ["용접공", "용접", "용접기능사"][:limit])
    seen_keywords: list[str] = []

    async def fake_get(self, url, params=None, **kwargs):
        seen_keywords.append(params["keyword"])
        # 두 번째 호출에서만 실제로 걸리는 상황을 흉내낸다 — 같은 eventNo가
        # 다른 호출에서도 겹쳐 나오는 경우까지 함께 확인한다.
        xml = _JOB_FAIR_XML if params["keyword"] in ("용접", "용접기능사") else "<empEvList><total>0</total></empEvList>"
        return httpx.Response(200, text=xml, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    results = await jic.search_job_fairs(JobInfoQueryParams(regions=[], keywords=["용접공"]))

    assert seen_keywords == ["용접공", "용접", "용접기능사"]
    # "용접"과 "용접기능사" 두 호출 모두 같은 eventNo(49160)를 돌려주므로
    # 중복 제거되어 결과는 1건이어야 한다.
    assert len(results) == 1
    assert results[0].source_key == "49160"


@pytest.mark.asyncio
async def test_search_job_fairs_unmapped_keyword_makes_exactly_one_call(monkeypatch):
    """테이블에 없는 키워드는 오늘과 동일하게 호출 1회 — 회귀 가드."""
    calls = {"n": 0}

    async def fake_get(self, url, params=None, **kwargs):
        calls["n"] += 1
        return httpx.Response(200, text=_JOB_FAIR_XML, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await jic.search_job_fairs(JobInfoQueryParams(regions=[], keywords=["듣도보도못한직업명"]))

    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_search_public_recruitment_parses_real_shaped_response(monkeypatch):
    _mock_get(monkeypatch, _PUBLIC_RECRUITMENT_XML)
    results = await jic.search_public_recruitment()
    assert results[0].title == "2026년 신규직원 채용"
    assert results[0].subtitle == "농업협동조합중앙회"
    assert results[0].detail_url == "https://nhcenter.incruit.com/hire/1"
    assert "규모: 대기업" in results[0].meta_lines
    assert results[0].source_key == "177320"


@pytest.mark.asyncio
async def test_search_public_recruitment_companies_parses_real_shaped_response(monkeypatch):
    _mock_get(monkeypatch, _PUBLIC_RECRUITMENT_COMPANY_XML)
    results = await jic.search_public_recruitment_companies()
    assert results[0].title == "한독헬스케어"
    assert "헬스케어" in results[0].meta_lines[-1]
    # 고용24에는 이 카테고리의 공개 상세 페이지가 없어서, 응답이 주는 기업
    # 채용 홈페이지를 상세 링크로 쓴다.
    assert results[0].detail_url == "https://handok.recruiter.co.kr/career/company"
    assert results[0].source_key == "E000026363"


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
    # 응답에 링크 필드가 없고 고용24에도 기업별 공개 상세가 없다 — 추측한
    # 주소로 보내느니 안 눌리는 카드로 둔다. 사업자번호는 중복 제거용으로만 쓴다.
    assert results[0].detail_url is None
    assert results[0].source_key == "3038515748"


@pytest.mark.asyncio
async def test_search_promising_smes_sends_the_region_when_params_have_one(monkeypatch):
    """2026-09-13 실측 확인: region=<광역 2자리>000(5자리)이 반영된다."""
    captured = {}

    async def fake_get(self, url, params=None, **kwargs):
        captured.update(params or {})
        return httpx.Response(200, text=_PROMISING_SME_XML, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await jic.search_promising_smes(JobInfoQueryParams(regions=["경기"], keywords=[]))
    assert captured["region"] == "41000"


@pytest.mark.asyncio
async def test_search_promising_smes_sends_no_region_when_params_is_none(monkeypatch):
    captured = {}

    async def fake_get(self, url, params=None, **kwargs):
        captured.update(params or {})
        return httpx.Response(200, text=_PROMISING_SME_XML, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await jic.search_promising_smes(limit=50)
    assert "region" not in captured


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
    # 유형(meta 첫 줄)이 달라서 서로 합쳐지지 않는다.
    assert len(results) == 4
    assert {r.meta_lines[0] for r in results} == {
        "유형: 국민내일배움카드", "유형: 사업주훈련", "유형: 국가인적자원개발컨소시엄", "유형: 일학습병행",
    }


@pytest.mark.asyncio
async def test_training_card_shows_the_course_name_not_the_institution(monkeypatch):
    """예전엔 subTitle(훈련기관명 "평화요양보호사교육원")을 제목으로 써서 무슨
    과정인지 알 수 없었다. 과정명은 title에 따로 온다(실응답 확인)."""
    _mock_get(monkeypatch, _TRAINING_XML)
    result = (await jic.search_training_courses())[0]

    assert result.title == "요양보호사자격취득과정"
    assert result.subtitle == "평화요양보호사교육원"
    assert result.meta_lines == [
        "유형: 국민내일배움카드",
        "기간: 2026-09-11 ~ 2027-01-10",
        "지역: 전북 전주시 완산구",
        "훈련비: 880,000원",
    ]
    # 기관 소개가 아니라 과정 상세로 연결한다.
    assert "selectTracseDetl" in result.detail_url
    # 과정 id + 회차 — 해시 대신 안정적인 중복 제거 키.
    assert result.source_key == "AIG20250000524076:9"
    # 개설 지역 — 맞춤 직업훈련의 지역 우선 정렬 입력.
    assert result.region_code == "52111"


@pytest.mark.asyncio
async def test_training_title_underscores_are_spaced_and_a_missing_title_falls_back(monkeypatch):
    underscored = _TRAINING_XML.replace(
        "<title>요양보호사자격취득과정</title>", "<title>2026년_(표준형)재직자_품질경영_L3</title>"
    ).replace("<courseMan>880000</courseMan>", "<courseMan>0</courseMan>")
    _mock_get(monkeypatch, underscored)
    result = (await jic.search_training_courses())[0]
    assert result.title == "2026년 (표준형)재직자 품질경영 L3"
    assert not any(m.startswith("훈련비") for m in result.meta_lines)  # 0원은 표시하지 않는다

    _mock_get(monkeypatch, _TRAINING_XML.replace("<title>요양보호사자격취득과정</title>", ""))
    result = (await jic.search_training_courses())[0]
    assert result.title == "평화요양보호사교육원"
    assert result.subtitle == "국민내일배움카드"  # 제목과 같은 기관명을 두 번 쓰지 않는다


@pytest.mark.asyncio
async def test_http_and_transport_errors_never_carry_the_auth_key(monkeypatch):
    """httpx 예외·raise_for_status 메시지에는 요청 URL(= authKey)이 들어 있다.
    피드 수집이 그 문자열을 last_error에 저장하고 /feed/sources가 보여준다."""
    monkeypatch.setattr(jic.settings, "worknet_job_posting_api_key", "secret-worknet-key")

    async def http_403(self, url, params=None, **kwargs):
        return httpx.Response(403, text="forbidden", request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(httpx.AsyncClient, "get", http_403)
    with pytest.raises(WorknetApiError) as exc_info:
        await jic.search_job_fairs()
    assert "secret-worknet-key" not in str(exc_info.value)

    async def timeout(self, url, params=None, **kwargs):
        raise httpx.ReadTimeout(f"timed out: {httpx.Request('GET', url, params=params).url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", timeout)
    with pytest.raises(WorknetApiError) as exc_info:
        await jic.search_job_fairs()
    assert "secret-worknet-key" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


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


@pytest.mark.asyncio
async def test_search_training_courses_raises_when_all_four_endpoints_fail(monkeypatch):
    """2026-09-12 검증: 훈련과정 4개가 전부 실패해도(그날의 고용24 전면 점검처럼)
    조용히 빈 목록으로 바뀌면, job_search.py 입장에선 "조건에 맞는 과정 0건"과
    구분이 안 된다. 다른 5개 카테고리처럼 여기서도 다시 던져서
    skipped_category_labels로 분류되게 한다."""
    async def always_fails(self, url, params=None, **kwargs):
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, text=_ERROR_XML_GO24, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", always_fails)

    with pytest.raises(WorknetApiError) as exc_info:
        await jic.search_training_courses()
    assert exc_info.value.category == "training_course"


@pytest.mark.asyncio
async def test_search_training_courses_raises_when_every_widening_stage_fails(monkeypatch):
    """조건이 있는 조회는 좁게 → 지역만 → 무조건 순으로 최대 3단계까지 넓혀본다.
    그 세 단계 전부에서 엔드포인트가 매번 실패하면(조건과 무관한 전면 장애),
    "조건에 맞는 과정 없음"이 아니라 여전히 오류로 분류돼야 한다."""
    async def always_fails(label, url, api_key, today, region=None, keyword=None):
        raise jic.WorknetApiError("training_course", "테스트용 오류")

    monkeypatch.setattr(jic, "_search_one_training_endpoint", always_fails)

    with pytest.raises(WorknetApiError):
        await jic.search_training_courses(JobInfoQueryParams(regions=["경기 북부"], keywords=["자바"]))


# --- 조회 조건을 실어 보내는 경로 (devlog 20) ---
#
# 예전에는 조건을 넘길 수단이 없어 전국 첫 20건을 무조건 받아왔다. 그래서
# "경기 북부 백엔드"라고 물어도 후보에 강원/경남 과정이 들어오니 관련성
# 판단이 아무리 정확해도 건질 게 없었다.


def test_no_params_means_one_unfiltered_combo():
    assert jic._training_combos(None) == [(None, None)]
    assert jic._training_combos(JobInfoQueryParams()) == [(None, None)]


def _no_synonym_expansion(monkeypatch):
    """조합/캡 로직을 동의어 테이블 내용과 분리한다 — 여긴 메커니즘을
    테스트하는 것이지 occupation_synonyms.py의 데이터를 테스트하는 게
    아니다(devlog 46)."""
    monkeypatch.setattr(jic, "expand_occupation_keyword", lambda kw, limit: [kw])


def test_each_same_dimension_value_becomes_its_own_combo(monkeypatch):
    # 같은 파라미터에 값을 여러 개 넣는 건 API가 지원하지 않는다 — 콤마는 0건,
    # 반복 파라미터는 첫 값만 적용된다(실측).
    _no_synonym_expansion(monkeypatch)
    combos = jic._training_combos(JobInfoQueryParams(regions=["서울", "부산"], keywords=["자바"]))

    assert [(r.area1, k) for r, k in combos] == [("11", "자바"), ("26", "자바")]


def test_keywords_without_a_region_still_produce_one_combo_each(monkeypatch):
    _no_synonym_expansion(monkeypatch)
    combos = jic._training_combos(JobInfoQueryParams(keywords=["자바", "디자인"]))

    assert [(r, k) for r, k in combos] == [(None, "자바"), (None, "디자인")]


def test_combo_count_is_capped(monkeypatch):
    # 조합 하나가 엔드포인트 4개 호출이 되므로 상한이 없으면 호출이 폭발한다.
    _no_synonym_expansion(monkeypatch)
    combos = jic._training_combos(JobInfoQueryParams(regions=["서울", "부산", "대구"], keywords=["자바", "디자인"]))

    assert len(combos) <= jic._MAX_TRAINING_COMBOS


def test_combos_expand_each_keyword_through_occupation_synonyms(monkeypatch):
    """srchTraProcessNm도 리터럴 부분일치라 job_fair와 같은 이유로 원본
    키워드마다 동의어를 얹는다(devlog 46) — _MAX_TRAINING_KEYWORD_VARIANTS와
    기존 _MAX_TRAINING_COMBOS 절단을 둘 다 지켜야 한다."""
    monkeypatch.setattr(
        jic, "expand_occupation_keyword",
        lambda kw, limit: {"용접공": ["용접공", "용접"], "제빵사": ["제빵사", "제과제빵"]}[kw][:limit],
    )
    combos = jic._training_combos(JobInfoQueryParams(keywords=["용접공", "제빵사"]))

    assert [(r, k) for r, k in combos] == [(None, "용접공"), (None, "용접"), (None, "제빵사")]
    assert len(combos) <= jic._MAX_TRAINING_COMBOS


def test_combos_do_not_expand_when_there_is_no_keyword(monkeypatch):
    calls = {"n": 0}

    def spy(kw, limit):
        calls["n"] += 1
        return [kw]

    monkeypatch.setattr(jic, "expand_occupation_keyword", spy)
    combos = jic._training_combos(JobInfoQueryParams(regions=["서울"]))

    assert calls["n"] == 0
    assert [(r.area1, k) for r, k in combos] == [("11", None)]


@pytest.mark.asyncio
async def test_filters_are_passed_through_to_every_endpoint(monkeypatch):
    _no_synonym_expansion(monkeypatch)
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
    _no_synonym_expansion(monkeypatch)
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
    _no_synonym_expansion(monkeypatch)

    async def fake_endpoint(label, url, api_key, today, region=None, keyword=None):
        # 조합이 달라도 같은 과정이 걸려 나오는 상황.
        return [JobInfoResult(title="같은 과정", subtitle="국민내일배움카드 · 고양", meta_lines=[])]

    monkeypatch.setattr(jic, "_search_one_training_endpoint", fake_endpoint)

    results = await jic.search_training_courses(JobInfoQueryParams(regions=["서울", "부산"]))

    assert len(results) == 1


@pytest.mark.asyncio
async def test_zero_filtered_results_falls_back_to_an_unfiltered_fetch(monkeypatch):
    # 고용24은 유효하지 않은 코드에도 에러가 아니라 빈 목록을 준다(실측: 통합 전
    # 광주 코드 29는 0건 — 지금은 12로 보낸다) — "코드가 틀렸다"와 "그 지역에 과정이 없다"를
    # 구분할 수 없으니, 조용히 빈 화면을 주는 대신 넓혀서 다시 받아온다.
    _no_synonym_expansion(monkeypatch)
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
