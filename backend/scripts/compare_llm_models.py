"""
운영 모델 후보 A/B 비교 — 같은 입력을 여러 모델에 돌려 속도와 품질을 나란히 본다.

사용법 (backend/ 에서):
    python scripts/compare_llm_models.py qwen2.5:32b qwen3.5:35b-a3b --think-off --out compare.md

- `.env`의 LOCAL_LLM_BASE_URL / Access 토큰으로 접속한다. 운영 판단은 반드시 Spark
  터널(https://llm.annswieteom.com)로 한다 — 노트북의 로컬 Ollama로 재면 노트북 GPU를 잰 것이다.
- 모델은 Spark에 미리 pull 해 둬야 한다(`ollama pull <모델>`은 Spark에서).
- 앱의 실제 경로(LocalOllamaProvider, 같은 프롬프트·파서)를 그대로 쓴다. 바꾸는 건 모델 이름뿐이다.
- `--think-off`: Qwen3 이후처럼 기본이 thinking인 모델용. 앱에서는 LOCAL_LLM_DISABLE_THINKING=true와 같다.
- 끝나면 .env의 운영 모델이 아닌 후보 모델은 Spark 메모리에서 내린다(keep_alive=0).

무엇을 보나:
- 속도: 호출별 wall(터널 포함), 출력 토큰, decode tok/s. 첫 호출(적재)은 워밍업으로 따로 뺀다.
- 정직성: 문서 문장마다 인용(fact_indices)이 유효한지, 사실 목록에 없는 숫자를 지어냈는지.
  이 두 가지는 자동 판정하고, 한국어 자연스러움은 출력 원문을 사람이 읽고 판단한다.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.llm import local_ollama  # noqa: E402
from app.services.llm.base import ConfirmedFact, InterviewContext, RecordExcerpt  # noqa: E402
from app.services.llm.local_ollama import LocalOllamaProvider  # noqa: E402

GAP_START, GAP_END = date(2025, 1, 1), date(2025, 8, 31)

FREE_TEXT = (
    "작년 초에 퇴사하고 한동안은 집 근처 카페에서 주 3일 오픈 아르바이트를 했어요. "
    "그러면서 저녁엔 정보처리기사 필기를 준비했고 5월에 붙었어요. 틈틈이 러닝도 했고요."
)

EXCERPT = RecordExcerpt(
    chunk_id="chunk-1",
    text="오픈 근무 3개월 차. 오늘은 원두 재고표를 엑셀로 정리해서 발주 실수를 줄였다. 사장님이 다음 달부터 재고 담당을 맡아 달라고 하셨다.",
    published_at=date(2025, 4, 12),
)

FACTS = [
    ConfirmedFact(id="f1", content="2025년 2월부터 5월까지 카페에서 주 3회 오픈 아르바이트를 했다", source_type="user_confirmed", fact_type="frequency"),
    ConfirmedFact(id="f2", content="원두 재고표를 엑셀로 정리해 발주 실수를 줄였다", source_type="record_cited", fact_type="task"),
    ConfirmedFact(id="f3", content="그 일을 계기로 사장님께 재고 담당을 맡았다", source_type="user_confirmed", fact_type="achievement"),
    ConfirmedFact(id="f4", content="손님이 몰리는 아침 시간에 주문이 밀려 동선을 다시 짰다", source_type="user_edited", fact_type="hardship_and_coping"),
]


def _context(facts: list[ConfirmedFact]) -> InterviewContext:
    return InterviewContext(
        session_id="compare",
        category_label="카페 아르바이트",
        gap_start=GAP_START,
        gap_end=GAP_END,
        confirmed_facts_so_far=facts,
        record_excerpts=[EXCERPT],
    )


@dataclass
class CaseResult:
    case: str
    wall: float = 0.0
    out_tokens: int = 0
    tok_s: float = 0.0
    ok: bool = True
    output: str = ""
    flags: list[str] = field(default_factory=list)


def _fabricated_numbers(text: str, facts: list[ConfirmedFact]) -> list[str]:
    """문장에 나오는 숫자 중 어떤 사실에도 없는 것 — 지어낸 수치의 싼 탐지기."""
    source = " ".join(f.content for f in facts)
    return [n for n in re.findall(r"\d+", text) if n not in source]


async def _run_cases(provider: LocalOllamaProvider) -> list[CaseResult]:
    results: list[CaseResult] = []

    async def run(case: str, coro_factory, render):
        result = CaseResult(case=case)
        stats_seen: list[dict] = []
        original = local_ollama._log_generation_stats

        def capture(label, model, wall, stats):
            stats_seen.append(stats)
            original(label, model, wall, stats)

        local_ollama._log_generation_stats = capture
        started = time.monotonic()
        try:
            value = await coro_factory()
            result.output, result.flags = render(value)
        except Exception as exc:  # 비교 스크립트라 실패도 결과로 남긴다
            result.ok = False
            result.output = f"{type(exc).__name__}: {exc}"
        finally:
            local_ollama._log_generation_stats = original
        result.wall = time.monotonic() - started
        result.out_tokens = sum(s.get("eval_count") or 0 for s in stats_seen)
        decode = sum(s.get("eval_duration") or 0 for s in stats_seen) / 1e9
        result.tok_s = result.out_tokens / decode if decode else 0.0
        results.append(result)

    await run(
        "extract_categories",
        lambda: provider.extract_categories(FREE_TEXT, GAP_START, GAP_END),
        lambda v: ("\n".join(f"- {c.category_type}: {c.custom_label}" for c in v), [] if v else ["빈 결과"]),
    )

    def render_facts(v):
        flags = [] if v else ["빈 결과"]
        if not any(f.based_on.type == "record" for f in v):
            flags.append("기록물 인용 없음(답변이 발췌와 일치하는데도)")
        return "\n".join(f"- ({f.fact_type}, {f.based_on.type}) {f.content}" for f in v), flags

    await run(
        "extract_facts",
        lambda: provider.extract_facts(
            _context(FACTS[:1]),
            "그 활동에서 구체적으로 어떤 일을 맡으셨나요?",
            "오픈 준비랑 음료 제조를 했고, 원두 재고표를 엑셀로 만들어서 발주 실수를 줄였어요.",
            "task",
        ),
        render_facts,
    )

    await run(
        "judge_drilldown",
        lambda: provider.judge_drilldown(_context(FACTS[:2])),
        lambda v: (f"should_ask={v.should_ask} / {v.question_text}", []),
    )

    await run(
        "draft_answer",
        lambda: provider.draft_answer(_context(FACTS[:2]), "그 과정에서 어려웠던 점과 어떻게 극복했는지 알려주세요."),
        lambda v: (v, [] if v.strip() else ["빈 결과"]),
    )

    def render_document(v):
        lines, flags = [], []
        for p in v.paragraphs:
            lines.append(f"[{p.topic}]")
            for s in p.sentences:
                valid = [i for i in s.fact_indices if 0 <= i < len(FACTS)]
                lines.append(f"- {s.text}  <- {[FACTS[i].id for i in valid]}")
                if not valid:
                    flags.append(f"인용 없는 문장: {s.text[:30]}")
                cited = [FACTS[i] for i in valid] or FACTS
                if made_up := _fabricated_numbers(s.text, cited):
                    flags.append(f"근거에 없는 숫자 {made_up}: {s.text[:30]}")
        return "\n".join(lines), flags

    await run(
        "generate_document",
        lambda: provider.generate_document(FACTS, "neutral", "카페 아르바이트"),
        render_document,
    )
    return results


async def _unload(model: str) -> None:
    base = settings.local_llm_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"{base}/api/generate", json={"model": model, "keep_alive": 0}, headers=settings.ollama_headers()
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="+", help="비교할 Ollama 모델 태그들")
    parser.add_argument("--think-off", action="store_true", help='요청에 "think": false를 싣는다')
    parser.add_argument("--out", help="마크다운 리포트를 저장할 경로")
    args = parser.parse_args()

    settings.local_llm_disable_thinking = args.think_off
    print(f"endpoint: {settings.local_llm_base_url}  think_off={args.think_off}\n")

    report: dict[str, list[CaseResult]] = {}
    for model in args.models:
        provider = LocalOllamaProvider()
        provider._model = model
        print(f"=== {model} — 워밍업(적재) 중 ...")
        warm_started = time.monotonic()
        try:
            await provider.extract_period("작년 3월부터 올해 1월까지 쉬었어요", date(2026, 9, 11))
            print(f"    워밍업 {time.monotonic() - warm_started:.1f}s")
        except Exception as exc:
            print(f"    워밍업 실패: {exc}")
        report[model] = await _run_cases(provider)
        for r in report[model]:
            status = "OK " if r.ok and not r.flags else ("FLAG" if r.ok else "FAIL")
            print(f"  [{status}] {r.case:<20} wall={r.wall:6.1f}s out={r.out_tokens:5d}tok {r.tok_s:5.1f} tok/s")
        print()

    lines = ["# LLM 모델 A/B 비교", "", f"- endpoint: `{settings.local_llm_base_url}`", f"- think_off: {args.think_off}", ""]
    lines.append("| case | " + " | ".join(args.models) + " |")
    lines.append("|---|" + "---|" * len(args.models))
    for i, case in enumerate(r.case for r in report[args.models[0]]):
        cells = []
        for model in args.models:
            r = report[model][i]
            mark = "" if r.ok and not r.flags else (" ⚠" if r.ok else " ✗")
            cells.append(f"{r.wall:.1f}s / {r.out_tokens}tok / {r.tok_s:.1f} tok/s{mark}")
        lines.append(f"| {case} | " + " | ".join(cells) + " |")
    lines.append(f"| **합계 wall** | " + " | ".join(f"{sum(r.wall for r in report[m]):.1f}s" for m in args.models) + " |")
    for model in args.models:
        lines += ["", f"## {model}"]
        for r in report[model]:
            lines += ["", f"### {r.case}", *(f"> ⚠ {flag}" for flag in r.flags), "", "```", r.output, "```"]
    text = "\n".join(lines)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\n저장: {args.out}")

    for model in args.models:
        if model != settings.local_llm_model_name:
            try:
                await _unload(model)
                print(f"내림: {model}")
            except Exception as exc:
                print(f"{model} 내리기 실패(직접 `ollama stop {model}`): {exc}")


if __name__ == "__main__":
    asyncio.run(main())
