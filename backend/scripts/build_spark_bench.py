"""Spark에서 바로 도는 모델 벤치 스크립트를 만든다 (devlog PersonA/09).

지금 코드의 실제 프롬프트를 앱 코드로 렌더링해 spark_model_bench.py.tmpl에 박아 넣는다.
결과물은 파이썬 기본 라이브러리만 쓰므로 Spark에 파일 하나만 옮기면 된다(localhost:11434 직접 호출).
프롬프트를 고친 뒤 모델을 다시 비교할 때 다시 만든다 — 결과물은 커밋하지 않는다(프롬프트가 박혀 금방 낡는다).

사용법 (backend/ 에서):
    .\\venv\\Scripts\\python.exe scripts/build_spark_bench.py <출력 경로>
    # Spark에서: python3 spark_model_bench.py qwen3.5:35b-a3b qwen2.5:32b --out bench.md
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.interview_question_bank import next_base_question  # noqa: E402
from app.services.llm import local_ollama  # noqa: E402
from app.services.llm.base import (  # noqa: E402
    TEMPERATURE_CREATIVE,
    TEMPERATURE_DETERMINISTIC,
    ConfirmedFact,
    RecordExcerpt,
)

_render = local_ollama._render
GAP_START, GAP_END = date(2025, 1, 1), date(2025, 8, 31)
LABEL = "카페 아르바이트"

# 공백기 채우기 첫 화면에 사용자가 적는 자유 입력
FREE_TEXT = (
    "작년 초에 퇴사하고 한동안은 집 근처 카페에서 주 3일 오픈 아르바이트를 했어요. "
    "그러면서 저녁엔 정보처리기사 필기를 준비했고 5월에 붙었어요. 틈틈이 러닝도 했고요."
)
# 기록물 단계에서 올린 블로그 글의 청크
EXCERPT = RecordExcerpt(
    chunk_id="3f1c9a2e-0b7d-4c55-9e0a-2d6b1f8c4a10",
    text="오픈 근무 3개월 차. 오늘은 원두 재고표를 엑셀로 정리해서 발주 실수를 줄였다. 사장님이 다음 달부터 재고 담당을 맡아 달라고 하셨다.",
    published_at=date(2025, 4, 12),
)
FACTS = [
    ConfirmedFact(id="f1", content="2025년 2월부터 5월까지 카페에서 주 3회 오픈 아르바이트를 했다", source_type="user_confirmed", fact_type="frequency"),
    ConfirmedFact(id="f2", content="원두 재고표를 엑셀로 정리해 발주 실수를 줄였다", source_type="record_cited", fact_type="task"),
    ConfirmedFact(id="f3", content="그 일을 계기로 사장님께 재고 담당을 맡았다", source_type="user_confirmed", fact_type="achievement"),
    ConfirmedFact(id="f4", content="손님이 몰리는 아침 시간에 주문이 밀려 동선을 다시 짰다", source_type="user_edited", fact_type="hardship_and_coping"),
]

# 웹사이트가 part_time 카테고리에서 실제로 던지는 고정 질문 순서
q_freq = next_base_question("part_time", set())
q_task = next_base_question("part_time", {"frequency"})
q_hard = next_base_question("part_time", {"frequency", "task"})

common = dict(category_label=LABEL, gap_start=GAP_START, gap_end=GAP_END, profile_summary=[])

cases = [
    {
        "name": "extract_categories",
        "step": "공백기 자유 입력 → 활동 카테고리 제안",
        "kind": "categories",
        "temperature": TEMPERATURE_DETERMINISTIC,
        "prompt": _render("extract_categories.jinja", free_text=FREE_TEXT, gap_start=GAP_START, gap_end=GAP_END),
    },
    {
        "name": "extract_facts",
        "step": f"질문「{q_task.text}」 답변 → 사실 초안 (블로그 기록 인용 기대)",
        "kind": "facts",
        "temperature": TEMPERATURE_DETERMINISTIC,
        "chunk_ids": [EXCERPT.chunk_id],
        "prompt": _render(
            "interview_extract_facts.jinja",
            **common,
            confirmed_facts_so_far=FACTS[:1],
            record_excerpts=[EXCERPT],
            question_text=q_task.text,
            answer_text="오픈 준비랑 음료 제조를 했고, 원두 재고표를 엑셀로 만들어서 발주 실수를 줄였어요.",
            fact_type_hint=q_task.fact_type,
        ),
    },
    {
        "name": "judge_drilldown",
        "step": "방금 답변을 더 파고들지 판단",
        "kind": "drilldown",
        "temperature": TEMPERATURE_DETERMINISTIC,
        "prompt": _render(
            "interview_drilldown.jinja",
            **common,
            confirmed_facts_so_far=FACTS[:2],
            asked_questions=[q_freq.text, q_task.text],
        ),
    },
    {
        "name": "draft_answer",
        "step": f"다음 질문「{q_hard.text}」 입력창 초안",
        "kind": "draft",
        "temperature": TEMPERATURE_CREATIVE,
        "prompt": _render(
            "interview_draft_answer.jinja",
            **common,
            confirmed_facts_so_far=FACTS[:2],
            record_excerpts=[EXCERPT],
            question_text=q_hard.text,
        ),
    },
    {
        "name": "judge_sufficiency",
        "step": "고정 질문이 끝난 뒤 이야기가 충분한지",
        "kind": "sufficiency",
        "temperature": TEMPERATURE_DETERMINISTIC,
        "prompt": _render("interview_sufficiency.jinja", category_label=LABEL, confirmed_facts_so_far=FACTS),
    },
    {
        "name": "generate_document",
        "step": "확정된 사실 4개 → STAR 경력기술서 (가장 오래 걸리는 호출)",
        "kind": "document",
        "temperature": TEMPERATURE_CREATIVE,
        "facts": [f.content for f in FACTS],
        "prompt": _render("final_document.jinja", confirmed_facts=FACTS, tone="neutral", category_label=LABEL),
    },
]

# the system message the app sends (local_ollama._generate)
src = open(local_ollama.__file__, encoding="utf-8").read()
system = (
    "You are an assistant that helps reconstruct career gap period narratives. "
    "Always respond in Korean. Output JSON only — no other text."
)
assert "helps reconstruct career gap period narratives. " in src and "Output JSON only — no other text." in src, (
    "system message drifted from local_ollama.py"
)

template = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "spark_model_bench.py.tmpl"), encoding="utf-8").read()
payload = json.dumps(
    {"system": system, "num_ctx": local_ollama._NUM_CTX, "cases": cases}, ensure_ascii=False, indent=1
)
assert "\nEOF\n" not in payload and '"""' not in payload
out = template.replace("__CASES_JSON__", payload)
open(sys.argv[1], "w", encoding="utf-8", newline="\n").write(out)
print(f"wrote {sys.argv[1]} ({len(out.encode('utf-8'))} bytes)")
