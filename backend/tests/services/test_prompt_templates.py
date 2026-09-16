"""프롬프트 템플릿 자체를 검사한다.

프롬프트 내용은 지금까지 어떤 테스트도 확인하지 않았고, 라이브 모델로 눌러보는
수동 확인에만 의존했다(devlog 18/19). 여기 있는 것들은 "이 지시가 사라지면
품질이 조용히 나빠진다"에 해당하는 tripwire다.
"""
from __future__ import annotations

from app.services.llm.base import JOB_INFO_CATEGORIES, JobInfoCandidate
from app.services.llm.local_ollama import _render

TEMPLATE = "select_relevant_job_info_results.jinja"


def _render_selection(candidates: list[JobInfoCandidate]) -> str:
    return _render(
        TEMPLATE,
        query="나는 백엔드 개발자야. 경기 북부에서 일자리를 구하고 싶어.",
        category_label="직업훈련과정",
        candidates=candidates,
    )


def _worst_case_candidates(count: int = 40) -> list[JobInfoCandidate]:
    # 훈련과정은 엔드포인트 4개 × 10건이라 40건이 상한이고(job_info_client),
    # public_recruitment_company는 회사소개 자유텍스트(coIntroSummaryCont)를
    # meta에 그대로 담아 한 줄이 수천 자가 될 수 있다 — 둘을 합친 최악 케이스.
    return [
        JobInfoCandidate(
            index=i,
            title=f"자바 웹 개발자 양성과정 {i}" + ("긴제목" * 30 if i == 3 else ""),
            subtitle="국민내일배움카드 · 고양시" + ("경기도 어딘가" * 10 if i == 3 else ""),
            meta_lines=(["회사소개: " + "가나다라마바사" * 300, "규모: 중소기업", "세번째는버려진다"] if i == 7 else []),
        )
        for i in range(count)
    ]


def test_select_relevant_prompt_has_worked_examples():
    rendered = _render_selection(_worst_case_candidates(3))

    assert "[예시]" in rendered
    assert '{ "relevant_indices": [1] }' in rendered
    assert '{ "relevant_indices": [1, 2] }' in rendered


def test_select_relevant_prompt_demands_exhaustive_selection():
    # 예시를 처음 넣었을 때 3b 모델이 정답 2건 중 1건만 고르는 과교정이 났다
    # (devlog 19). "전부 골라라" 지시 + 마지막 예시가 복수 선택인 것으로 고쳤으니,
    # 둘 중 하나라도 사라지면 그 회귀가 조용히 돌아온다.
    rendered = _render_selection(_worst_case_candidates(3))

    assert "전부" in rendered
    # "[USER]"는 예시 안내 문장에도 나오므로 줄 시작 기준으로 섹션 헤더를 찾는다.
    examples_block = rendered[: rendered.rindex("\n[USER]")]
    assert examples_block.rstrip().splitlines()[-1] == '출력: { "relevant_indices": [1, 2] }'


def test_select_relevant_prompt_renders_every_candidate():
    rendered = _render_selection(_worst_case_candidates())

    for i in range(40):
        assert f"\n{i}. " in rendered
    # 후보 사이에 빈 줄이 끼면 목록 길이가 배로 늘어난다(trim 없는 for 루프).
    assert "\n\n1. " not in rendered


def test_select_relevant_prompt_truncates_overlong_candidate_text():
    rendered = _render_selection(_worst_case_candidates())

    long_meta_line = next(ln for ln in rendered.splitlines() if ln.startswith("7. "))
    assert "…" in long_meta_line
    assert len(long_meta_line) < 200
    assert "세번째는버려진다" not in rendered  # meta_lines[:2]만 렌더된다


def test_select_relevant_prompt_stays_within_size_budget():
    # 누가 후보 줄에 필드를 더 붙이면 여기서 걸린다.
    rendered = _render_selection(_worst_case_candidates())

    assert len(rendered) < 9000


def test_select_relevant_prompt_ends_with_output_format():
    # 출력 형식 지시가 맨 끝에 있어야 모델이 그 형식으로 끝을 맺는다.
    rendered = _render_selection(_worst_case_candidates())

    assert rendered.rstrip().endswith('{ "relevant_indices": [번호, 번호, ...] }')


def test_query_params_prompt_lists_only_recognized_region_names():
    # 목록 밖의 지역명을 LLM이 만들면 코드 변환에서 조용히 버려지므로, 인식
    # 가능한 어휘를 프롬프트에 그대로 보여주고 그 안에서만 고르게 한다.
    from app.services.job_pipeline.regions import KNOWN_REGION_NAMES

    rendered = _render(
        "extract_job_info_query_params.jinja",
        query="경기 북부에서 자바 과정 있어?",
        known_regions=list(KNOWN_REGION_NAMES),
    )

    assert "경기 북부" in rendered
    assert "수도권" in rendered
    for name in KNOWN_REGION_NAMES:
        assert name in rendered
    # 검색으로 좁힐 수 없는 조건을 넣으라고 시키면 안 된다.
    assert "급여" in rendered  # "넣지 마라"는 지시가 남아 있는지


def test_classify_prompt_mentions_every_job_info_category():
    # 카테고리를 코드에 추가했는데 프롬프트에 안 적으면 LLM이 그걸 고를 수 없다.
    rendered = _render("classify_job_info_query.jinja", query="이직 준비 도움될 거 있어?")

    for category in JOB_INFO_CATEGORIES:
        assert category in rendered


def test_classify_prompt_handles_multi_topic_history():
    # 2026-09-15 실계정 재현 — 무관한 직무 4개(상담심리사/승강기정비사/
    # 게임기획자/배달라이더) 다음 "전기기사"를 물은 뒤 "그중에서 서울만"이라고
    # 하면 실패했다. "가장 최근 주제만 유효" 규칙과 그 예시가 사라지면 이
    # 회귀가 조용히 돌아온다.
    rendered = _render("classify_job_info_query.jinja", query="이직 준비 도움될 거 있어?")

    assert "가장 최근(마지막)" in rendered
    assert "전기기사" in rendered


def test_extract_prompt_keeps_only_the_most_recent_job_in_history():
    rendered = _render(
        "extract_job_info_query_params.jinja",
        query="이직 준비 도움될 거 있어?",
        known_regions=["서울"],
    )

    assert "가장 최근(마지막)" in rendered
    # 다중 주제 히스토리 예시가 실제로 존재하는지 — 없어지면 규칙만 남고
    # 모델이 따라야 할 구체적 사례가 사라진다.
    assert '{ "regions": ["서울"], "keywords": ["전기기사"] }' in rendered


def test_select_relevant_prompt_handles_multi_topic_history():
    rendered = _render_selection(_worst_case_candidates(3))

    assert "가장 최근(마지막)" in rendered
    # 새 예시가 기존 마지막 예시(exhaustive selection) 앞에 들어갔는지 —
    # 뒤에 붙으면 devlog 45와 같은 회귀가 재발한다(아래 테스트가 별도로 확인).
    assert '{ "relevant_indices": [0] }' in rendered


# --- devlog 54: 프로필 공개·모순 시 폐기 + 한국어 전용 지시 ------------------

_INTERVIEW_BASE_KWARGS = dict(
    category_label="아르바이트",
    gap_start="2025-01-01",
    gap_end="2025-06-30",
    confirmed_facts_so_far=[{"fact_type": "task", "content": "카페에서 일했다"}],
    record_excerpts=[],
    asked_questions=["이전 질문"],
)


def _render_followup(profile_summary: list[str] | None = None) -> str:
    return _render(
        "interview_followup_question.jinja",
        profile_summary=profile_summary or [],
        **_INTERVIEW_BASE_KWARGS,
    )


def _render_drilldown(profile_summary: list[str] | None = None) -> str:
    return _render(
        "interview_drilldown.jinja",
        profile_summary=profile_summary or [],
        **_INTERVIEW_BASE_KWARGS,
    )


def test_followup_prompt_profile_block_requires_disclosure_and_staleness_check():
    rendered = _render_followup(profile_summary=["희망직무: 백엔드 개발자"])

    assert "질문 문장 자체에 자연스럽게 그 사실을 밝혀라" in rendered
    assert "모순되면 프로필 쪽을 낡은 정보로 보고 더 이상 참고하지 마라" in rendered


def test_drilldown_prompt_profile_block_requires_disclosure_and_staleness_check():
    rendered = _render_drilldown(profile_summary=["희망직무: 백엔드 개발자"])

    assert "질문 문장 자체에 자연스럽게 그 사실을 밝혀라" in rendered
    assert "모순되면 프로필 쪽을 낡은 정보로 보고 더 이상 참고하지 마라" in rendered


def test_extract_facts_prompt_forbids_language_mixing():
    rendered = _render(
        "interview_extract_facts.jinja",
        category_label="아르바이트",
        gap_start="2025-01-01",
        gap_end="2025-06-30",
        confirmed_facts_so_far=[],
        record_excerpts=[],
        question_text="어떤 일을 하셨나요?",
        answer_text="카페에서 일했어요",
        fact_type_hint="task",
    )

    assert "한국어로만" in rendered


def test_followup_prompt_forbids_language_mixing():
    assert "한국어로만" in _render_followup()


def test_drilldown_prompt_forbids_language_mixing():
    assert "한국어로만" in _render_drilldown()


def test_probe_activity_prompt_forbids_language_mixing():
    rendered = _render(
        "probe_activity_question.jinja",
        free_text="잘 모르겠어요",
        gap_start="2025-01-01",
        gap_end="2025-06-30",
        focus="아르바이트나 단기 근로",
    )

    assert "한국어로만" in rendered
