"""
취업 정보 검색(대화형) 분류·추출 정확도 평가 — 실제 Ollama로 골든셋을 돌려 점수를 낸다.

사용법 (backend/ 에서):
    python scripts/eval_job_search.py --out job_search_eval.md

- `.env`의 LOCAL_LLM_BASE_URL/Access 토큰으로 접속한다. 로컬 dev의 약한 모델
  (qwen2.5:3b-instruct)로는 품질 판단 자체가 무의미하다 — 반드시 실제 Spark
  터널(운영 모델)로 돌려야 한다(04_local_dev_environment.md와 같은 이유).
- compare_llm_models.py와 같은 스타일: 앱의 실제 경로(LocalOllamaProvider, 같은
  프롬프트)를 그대로 쓰고, 자동으로 판정 가능한 것만 자동 채점하고 나머지는
  마크다운 리포트에 원문을 남겨 사람이 읽고 판단한다.

이전에는 취업 정보 검색 쪽에 이런 골든셋이 전혀 없었다(2026-09-14 리포트 조사) —
`test_job_search.py`/`test_local_ollama.py`는 전부 FakeLLMProvider나 캔ned HTTP
응답에 대해서만 돌아 배관(분류 결과를 올바르게 카드로 조립하는지)만 검증하고,
실제 모델이 실제로 올바른 카테고리/지역/직무를 골라내는지는 이번이 처음이다.

무엇을 자동 채점하나:
- 분류(classify_job_info_query): 기대 카테고리 집합과의 정밀도/재현율,
  unsupported_note 존재 여부가 기대와 맞는지, **카테고리가 선택됐는데
  unsupported_note가 그 카테고리로 커버되는 지역/직무를 그대로 언급하는 모순**
  (2026-09-14에 실제로 발견된 버그 패턴, job_search.py의 사후 방어선과 별개로
  프롬프트 자체의 품질을 잰다).
- 추출(extract_job_info_query_params): 기대 지역 집합과의 일치.
- 관련성 판정(select_relevant_job_info_results): "조건 없는 질문"(예: "강소기업
  추천해줘")을 줬을 때 후보 전체를 관련 있다고 고르는지(2026-09-15 리포트 —
  비교할 기준이 아예 없는 걸 "전부 무관하다"로 잘못 해석해 빈 배열을 내던
  버그). classify/extract와 달리 합성 후보 리스트로 직접 이 함수만 호출한다.
자동 채점 못 하는 것(unsupported_note 문구가 자연스러운지 등)은 리포트에 원문을
남겨 사람이 읽는다.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings  # noqa: E402
from app.services.llm.base import JobInfoCandidate  # noqa: E402
from app.services.llm.local_ollama import LocalOllamaProvider  # noqa: E402


@dataclass
class Case:
    label: str
    query: str
    history: list[str] = field(default_factory=list)
    profile_hint: list[str] = field(default_factory=list)
    #: 정확히 이 집합이어야 한다고 확신하는 경우만 채운다. None이면 카테고리
    #: 채점을 건너뛰고(예: 완전히 새로운 질의라 정답이 모호함) 원문만 리포트에 남긴다.
    expected_categories: frozenset[str] | None = None
    unsupported_expected: bool = False
    #: extract_job_info_query_params도 같이 채점하고 싶을 때만.
    expected_regions: frozenset[str] | None = None
    #: True면 extract_job_info_query_params도 호출해서, unsupported_note가
    #: 방금 추출한 keywords 중 하나를 그대로 미지원 사유로 지어내는 모순이
    #: 있는지 검사한다(2026-09-15 리포트 — 지역 모순과 같은 패턴이 직무명에도
    #: 있었다).
    check_keyword_contradiction: bool = False


# 2026-09-13/14 실계정 라이브 테스트에서 실제로 썼던 12개 질의 + 다양성을 더한
# 케이스. 지역·직군·프로필 인용 여부·개발의도 부합/불일치를 고루 섞는다.
CASES: list[Case] = [
    Case(
        "self_referential_with_profile",
        "내 맞춤 정보에 따라 취업 정보를 찾아줘",
        profile_hint=["희망직무: 백엔드 프로그래머", "희망지역: 경기 북부, 서울"],
        expected_categories=frozenset({"public_recruitment", "promising_sme", "training_course"}),
    ),
    Case(
        "explicit_matches_profile",
        "경기 북부 프로그래머가 취직할 수 있는 강소기업을 찾아줘",
        profile_hint=["희망직무: 백엔드 프로그래머", "희망지역: 경기 북부, 서울"],
        expected_categories=frozenset({"promising_sme"}),
        expected_regions=frozenset({"경기 북부"}),
    ),
    Case(
        "unsupported_concept_only",
        "부산에서 카페 매니저로 일할 수 있는 곳 있어?",
        expected_categories=frozenset(),
        unsupported_expected=True,
    ),
    Case(
        "mixed_supported_and_unsupported",
        "대구 카페 알바랑 관련 직업훈련 같이 알려줘",
        expected_categories=frozenset({"training_course"}),
        unsupported_expected=True,
        expected_regions=frozenset({"대구"}),
    ),
    Case(
        "broad_career_change",
        "이직 준비하는데 도움될 거 있어?",
        expected_categories=frozenset({"training_course", "job_seeker_program", "promising_sme"}),
    ),
    Case(
        "colloquial_region",
        "충청권에서 물류창고 관리직 채용 있어?",
        expected_categories=frozenset({"public_recruitment"}),
        expected_regions=frozenset({"충청권"}),
    ),
    Case(
        "specific_region_and_job",
        "제주도에서 요양보호사 자격증 훈련과정 있어?",
        profile_hint=["희망직무: 백엔드 프로그래머", "희망지역: 경기 북부, 서울"],
        expected_categories=frozenset({"training_course"}),
        expected_regions=frozenset({"제주"}),
    ),
    Case(
        "completely_off_topic",
        "오늘 저녁 뭐 먹을지 추천해줘",
        expected_categories=frozenset(),
        unsupported_expected=True,
    ),
    Case(
        "conflicts_with_profile_explicit",
        "전북 지역 마케팅 전문가 채용행사 있어?",
        profile_hint=["희망직무: 백엔드 프로그래머", "희망지역: 경기 북부, 서울"],
        expected_categories=frozenset({"job_fair"}),
        expected_regions=frozenset({"전북"}),
    ),
    Case(
        "career_advice_not_a_listing",
        "연봉 협상 어떻게 해야 할지 조언해줘",
        expected_categories=frozenset(),
    ),
    Case(
        # 2026-09-14에 실제로 발견된 버그: 카테고리는 맞게 고르면서도
        # unsupported_note에 "인천은 지원 안 함"을 지어냈다 — 회귀 감시용.
        "profile_conflict_must_not_be_unsupported",
        "내 프로필 말고 인천에서 디자이너 뽑는 데 있어?",
        profile_hint=["희망직무: 백엔드 프로그래머", "희망지역: 경기 북부, 서울"],
        expected_categories=frozenset({"public_recruitment"}),
        unsupported_expected=False,
        expected_regions=frozenset({"인천"}),
    ),
    Case(
        "vague_region",
        "지방에서 신입 개발자 뽑는 데 있을까?",
        profile_hint=["희망직무: 백엔드 프로그래머", "희망지역: 경기 북부, 서울"],
        expected_categories=frozenset({"public_recruitment", "promising_sme"}),
    ),
    # --- 후속 질문(history) 케이스 — devlog 44 전에는 아예 이해 못 했다. ---
    Case(
        "followup_adds_region",
        "그럼 서울도 같이 봐줘",
        history=["경기 프로그래머 강소기업 찾아줘"],
        expected_categories=frozenset({"promising_sme"}),
        expected_regions=frozenset({"경기", "서울"}),
    ),
    Case(
        "followup_narrows_job",
        "그중에서도 백엔드만",
        history=["신입 개발자 뽑는 공채 있어?"],
        expected_categories=frozenset({"public_recruitment"}),
    ),
    # --- 그 외 다양성: 직군/지역/요구사항을 더 넓힌다. ---
    Case(
        "designer_seoul",
        "서울에서 UX 디자이너 채용 공고 있어?",
        expected_categories=frozenset({"public_recruitment"}),
        expected_regions=frozenset({"서울"}),
    ),
    Case(
        "marketing_training_gangwon",
        "강원도에서 들을 수 있는 마케팅 관련 훈련과정 알려줘",
        expected_categories=frozenset({"training_course"}),
        expected_regions=frozenset({"강원"}),
    ),
    Case(
        "resume_consulting",
        "이력서 첨삭이나 면접 컨설팅 받을 수 있는 데 있어?",
        expected_categories=frozenset({"job_seeker_program"}),
    ),
    Case(
        "sme_no_region",
        "강소기업 정보 아무거나 보여줘",
        expected_categories=frozenset({"promising_sme"}),
    ),
    Case(
        "job_fair_specific_date_phrase",
        "이번 달 채용박람회 일정 있어?",
        expected_categories=frozenset({"job_fair"}),
    ),
    Case(
        "nursing_care_ulsan",
        "울산에서 간호조무사 훈련 받을 수 있는 곳 있어?",
        expected_categories=frozenset({"training_course"}),
        expected_regions=frozenset({"울산"}),
    ),
    # --- 2026-09-15 실측 회귀 감시 ---
    Case(
        # "인천 초등학교 교사 채용 소식 있어?"가 categories=["public_recruitment"]를
        # 정확히 고르고도 unsupported_note에 "초등학교 교사 채용정보"라고 방금
        # 고른 그 직무를 미지원이라 지어냈다 — 지역 모순과 같은 패턴.
        "job_title_contradiction_elementary_teacher",
        "인천 초등학교 교사 채용 소식 있어?",
        expected_categories=frozenset({"public_recruitment"}),
        unsupported_expected=False,
        check_keyword_contradiction=True,
    ),
    Case(
        # "지역 없이 아무거나" 스타일 — 구체적 조건이 하나도 없으면 classify가
        # 빈 배열로 포기하지 않는지(원래도 잘 됐어야 하지만, select_relevant
        # 쪽 회귀와 짝을 맞춰 같이 감시한다).
        "no_criteria_recommend_anything",
        "강소기업 추천해줘",
        expected_categories=frozenset({"promising_sme"}),
    ),
]


@dataclass
class RelevanceCase:
    """select_relevant_job_info_results 전용 골든셋 — classify/extract와 달리
    실제 고용24 조회 없이 합성 후보 리스트로 이 함수 하나만 직접 부른다."""

    label: str
    query: str
    category_label: str
    #: (title, subtitle) 쌍 — 실제 응답처럼 meta_lines까지는 안 만든다.
    candidates: list[tuple[str, str]]
    history: list[str] = field(default_factory=list)
    #: 기대하는 relevant_indices. None이면 "전부 다 골라야 한다"(조건 없는
    #: 질문 케이스).
    expected_indices: frozenset[int] | None = None


RELEVANCE_CASES: list[RelevanceCase] = [
    RelevanceCase(
        # 2026-09-15 리포트: "강소기업 추천해줘"처럼 비교할 조건이 아예 없으면
        # "관련 있는 게 하나도 없다"로 오인해 빈 배열을 낸 버그.
        "no_criteria_selects_everything",
        "강소기업 추천해줘",
        "강소기업",
        [
            ("(주)코리아메디케어", "서울 중구 · 정보서비스업"),
            ("(주)넷츠", "서울 강남구 · 컴퓨터 프로그래밍"),
            ("덕산네오룩스(주)", "충남 천안시 · 전자부품 제조업"),
        ],
        expected_indices=frozenset({0, 1, 2}),
    ),
    RelevanceCase(
        "no_criteria_job_fair",
        "요즘 채용행사 뭐 있어?",
        "채용행사",
        [
            ("2026 부산청년 메가(MEGA) 채용 박람회", "부산/경남 지역"),
            ("대형물류센터 일자리수요데이", "부산/경남 지역"),
        ],
        expected_indices=frozenset({0, 1}),
    ),
    RelevanceCase(
        # 조건이 하나라도 있으면(직무만 있어도) 이 예외가 적용되면 안 된다 —
        # 새 지시가 기존 필터링 능력을 퇴화시키지 않는지 확인하는 회귀 가드.
        "still_filters_when_a_criterion_exists",
        "간호사 채용 관련 강소기업 있어?",
        "강소기업",
        [
            ("(주)코리아메디케어", "서울 중구 · 의료기기 유통업"),
            ("덕산네오룩스(주)", "충남 천안시 · 전자부품 제조업"),
        ],
        expected_indices=frozenset({0}),
    ),
]


def _score_relevance(case: RelevanceCase, got_indices: list[int]) -> list[str]:
    if case.expected_indices is None:
        return []
    got = frozenset(got_indices)
    if got != case.expected_indices:
        return [f"relevant_indices 불일치: 기대 {sorted(case.expected_indices)}, 실제 {sorted(got)}"]
    return []


@dataclass
class RelevanceScore:
    label: str
    query: str
    relevant_indices: list[int]
    problems: list[str]


async def _run_relevance(provider: LocalOllamaProvider) -> list[RelevanceScore]:
    scores = []
    for case in RELEVANCE_CASES:
        candidates = [
            JobInfoCandidate(index=i, title=title, subtitle=subtitle, meta_lines=[])
            for i, (title, subtitle) in enumerate(case.candidates)
        ]
        try:
            indices = await provider.select_relevant_job_info_results(
                case.query, case.category_label, candidates, case.history
            )
        except Exception as exc:
            scores.append(RelevanceScore(case.label, case.query, [], [f"select_relevant 실패: {exc}"]))
            continue
        problems = _score_relevance(case, indices)
        scores.append(RelevanceScore(case.label, case.query, indices, problems))
    return scores


@dataclass
class CaseScore:
    label: str
    query: str
    categories: list[str]
    unsupported_note: str | None
    regions: list[str] | None
    keywords: list[str] | None
    problems: list[str]


def _score_categories(
    case: Case, categories: list[str], unsupported_note: str | None, keywords: list[str] | None = None
) -> list[str]:
    problems = []
    got = frozenset(categories)
    if case.expected_categories is not None and got != case.expected_categories:
        missing = case.expected_categories - got
        extra = got - case.expected_categories
        if missing:
            problems.append(f"카테고리 누락: {sorted(missing)}")
        if extra:
            problems.append(f"카테고리 과다: {sorted(extra)}")
    has_note = unsupported_note is not None
    if has_note != case.unsupported_expected:
        problems.append(f"unsupported_note 기대={case.unsupported_expected} 실제={has_note}")
    # 핵심 회귀 감시: 카테고리가 선택됐는데 unsupported_note가 이미 추출된
    # 지역명을 그대로 언급하면 모순이다(2026-09-14 버그 패턴).
    if got and unsupported_note and case.expected_regions:
        hit = [r for r in case.expected_regions if r in unsupported_note]
        if hit:
            problems.append(f"모순: 카테고리 선택됐는데 unsupported_note가 지역 {hit}을 미지원이라 언급함")
    # 같은 패턴이 직무명에도 있었다(2026-09-15 리포트) — 카테고리가 선택됐는데
    # unsupported_note가 방금 추출한 keywords 중 하나를 그대로 미지원 사유로
    # 지어내면 모순이다.
    if got and unsupported_note and keywords:
        hit = [k for k in keywords if k in unsupported_note]
        if hit:
            problems.append(f"모순: 카테고리 선택됐는데 unsupported_note가 직무 {hit}를 미지원이라 언급함")
    return problems


def _score_regions(case: Case, regions: list[str]) -> list[str]:
    if case.expected_regions is None:
        return []
    got = frozenset(regions)
    if not (case.expected_regions & got):
        return [f"지역 불일치: 기대 {sorted(case.expected_regions)}, 실제 {sorted(got)}"]
    return []


async def _run(provider: LocalOllamaProvider) -> list[CaseScore]:
    scores = []
    for case in CASES:
        problems: list[str] = []
        try:
            categories, unsupported_note = await provider.classify_job_info_query(
                case.query, case.profile_hint, case.history
            )
        except Exception as exc:
            scores.append(CaseScore(case.label, case.query, [], None, None, None, [f"classify 실패: {exc}"]))
            continue
        category_names = [c.category for c in categories]

        regions: list[str] | None = None
        keywords: list[str] | None = None
        if case.expected_regions is not None or case.check_keyword_contradiction:
            try:
                from app.services.job_pipeline.regions import KNOWN_REGION_NAMES

                params = await provider.extract_job_info_query_params(
                    case.query, list(KNOWN_REGION_NAMES), case.history
                )
                regions, keywords = params.regions, params.keywords
                problems += _score_regions(case, regions)
            except Exception as exc:
                problems.append(f"extract 실패: {exc}")

        problems += _score_categories(case, category_names, unsupported_note, keywords)

        scores.append(CaseScore(case.label, case.query, category_names, unsupported_note, regions, keywords, problems))
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="마크다운 리포트를 저장할 경로")
    args = parser.parse_args()

    print(f"endpoint: {settings.local_llm_base_url}  model: {settings.local_llm_model_name}\n")
    provider = LocalOllamaProvider()
    scores = asyncio.run(_run(provider))
    relevance_scores = asyncio.run(_run_relevance(provider))

    passed = sum(1 for s in scores if not s.problems)
    relevance_passed = sum(1 for s in relevance_scores if not s.problems)
    print(f"결과(분류/추출): {passed}/{len(scores)} 통과")
    print(f"결과(관련성 판정): {relevance_passed}/{len(relevance_scores)} 통과\n")

    lines = [
        "# 취업 정보 검색 분류·추출 평가",
        "",
        f"- endpoint: `{settings.local_llm_base_url}`",
        f"- model: `{settings.local_llm_model_name}`",
        f"- 결과(분류/추출): **{passed}/{len(scores)} 통과**",
        f"- 결과(관련성 판정): **{relevance_passed}/{len(relevance_scores)} 통과**",
        "",
        "| case | query | categories | unsupported_note | 문제 |",
        "|---|---|---|---|---|",
    ]
    for s in scores:
        mark = "" if not s.problems else " ⚠"
        note = (s.unsupported_note or "")[:40]
        problems = "; ".join(s.problems) or "-"
        lines.append(f"| {s.label}{mark} | {s.query} | {', '.join(s.categories) or '(없음)'} | {note} | {problems} |")

    lines += [
        "",
        "## 관련성 판정(select_relevant_job_info_results)",
        "",
        "| case | query | relevant_indices | 문제 |",
        "|---|---|---|---|",
    ]
    for s in relevance_scores:
        mark = "" if not s.problems else " ⚠"
        problems = "; ".join(s.problems) or "-"
        lines.append(f"| {s.label}{mark} | {s.query} | {s.relevant_indices} | {problems} |")

    lines += ["", "## 실패/경고 상세"]
    for s in scores:
        if not s.problems:
            continue
        lines += [
            "",
            f"### {s.label}",
            f"- query: {s.query}",
            f"- categories: {s.categories}",
            f"- unsupported_note: {s.unsupported_note!r}",
            f"- regions: {s.regions}",
            f"- keywords: {s.keywords}",
            *(f"- ⚠ {p}" for p in s.problems),
        ]
    for s in relevance_scores:
        if not s.problems:
            continue
        lines += [
            "",
            f"### {s.label} (관련성 판정)",
            f"- query: {s.query}",
            f"- relevant_indices: {s.relevant_indices}",
            *(f"- ⚠ {p}" for p in s.problems),
        ]

    text = "\n".join(lines)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
