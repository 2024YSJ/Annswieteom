"""관련성 판정 LLM에 넘기기 전, 넓힌 후보 풀을 값싸게 미리 추리는 1차 필터.

devlog 52: `public_recruitment`/`public_recruitment_company`/`job_seeker_program`/
`promising_sme`은 서버 쪽 직무 필터가 없어(devlog 39/46), job_info_client.py가
받아오는 원본 풀을 넓혀도(_RAW_POOL_LIMIT=300, 다중 페이지 병합) 그 전체를
select_relevant_job_info_results 프롬프트에 그대로 넣으면 프롬프트 크기·
지연시간이 그대로 늘어난다. 이 모듈은 넓힌 후보 풀에서 키워드/지역 부분일치로
명백히 무관해 보이는 항목을 미리 추려, LLM에는 지금까지와 비슷한 크기의
후보만 넘기면서도 그 후보가 훨씬 넓은 풀에서 뽑힌 것이게 한다.

최종 관련성 판단 권한은 항상 LLM에 있다(devlog 18) — 이 필터는 예비 단계일
뿐 정밀한 매칭을 시도하지 않는다. 통과한 게 너무 적으면 원본 풀 앞부분으로
그냥 폴백한다(필터가 너무 빡빡해서 진짜 있는 결과를 지워버리는 것을 방지).
"""
from __future__ import annotations

from app.services.job_pipeline.job_info_client import JobInfoResult
from app.services.job_pipeline.occupation_synonyms import expand_occupation_keyword
from app.services.job_pipeline.regions import region_match_terms
from app.services.llm.base import JobInfoQueryParams

#: 키워드 하나를 몇 개 표현까지 펼쳐서 매칭에 쓸지 — job_fair의
#: _MAX_JOB_FAIR_KEYWORD_VARIANTS와 같은 이유로 넉넉하게 잡는다(이건 API
#: 호출이 아니라 로컬 문자열 비교라 늘려도 비용이 거의 없다).
_MAX_KEYWORD_VARIANTS_PER_TERM = 5

# "통과한 게 적으면 폴백"이 아니라 "하나도 없으면 폴백"이다 — 실제로 3~4건만
# 맞아떨어지는 건 정상적인 좁은 결과이고(그대로 LLM에 넘기는 게 30건짜리
# 미필터 목록보다 낫다), 관련 있는 게 정말 하나도 없을 때만 "필터 자체가
# 이 데이터엔 안 맞는다"(예: public_recruitment/public_recruitment_company처럼
# 애초에 지역 정보가 응답에 없는 카테고리, devlog 52)고 보고 원본 풀
# 앞부분으로 되돌아간다. 그래도 결과가 부족하면 job_search.py의
# _MIN_RELEVANT_BEFORE_WIDENING widen 재시도가 별도로 넓혀준다.


def _searchable_text(result: JobInfoResult) -> str:
    return " ".join([result.title, result.subtitle, *result.meta_lines])


def _keyword_terms(keywords: list[str]) -> list[str]:
    terms: list[str] = []
    for keyword in keywords:
        terms.extend(expand_occupation_keyword(keyword, limit=_MAX_KEYWORD_VARIANTS_PER_TERM))
    return terms


def prefilter_candidates(
    raw: list[JobInfoResult], query_params: JobInfoQueryParams | None, limit: int
) -> list[JobInfoResult]:
    """`raw`(넓은 후보 풀)에서 LLM에 넘길 만큼(`limit`)만 추린다.

    조건(키워드/지역)이 아예 없으면 devlog 49의 "조건 없으면 전부 관련"
    원칙과 같은 이유로 필터를 걸지 않고 앞에서부터 `limit`개를 그대로
    돌려준다. 키워드나 지역 중 하나라도 일치하면 통과시킨다(OR) — 최종
    "지역·직무를 다 만족해야 한다"는 판단은 LLM이 하므로(devlog 45), 여기서는
    후보를 넓게 살려 재현율을 지키는 쪽을 우선한다.
    """
    if query_params is None or (not query_params.keywords and not query_params.regions):
        return raw[:limit]

    keyword_terms = _keyword_terms(query_params.keywords)
    region_terms = region_match_terms(query_params.regions)

    def _matches(result: JobInfoResult) -> bool:
        text = _searchable_text(result)
        if keyword_terms and any(term in text for term in keyword_terms):
            return True
        if region_terms and any(term in text for term in region_terms):
            return True
        return False

    matched = [r for r in raw if _matches(r)]
    if not matched:
        return raw[:limit]
    return matched[:limit]
