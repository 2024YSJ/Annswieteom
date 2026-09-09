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


def test_classify_prompt_mentions_every_job_info_category():
    # 카테고리를 코드에 추가했는데 프롬프트에 안 적으면 LLM이 그걸 고를 수 없다.
    rendered = _render("classify_job_info_query.jinja", query="이직 준비 도움될 거 있어?")

    for category in JOB_INFO_CATEGORIES:
        assert category in rendered
