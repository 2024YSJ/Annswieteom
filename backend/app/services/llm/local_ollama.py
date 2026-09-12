from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.models.activity_category import CATEGORY_TYPES
from app.services.llm.ollama_gate import OLLAMA_GATE
from app.services.llm.base import (
    AttributeCandidate,
    BasedOn,
    CategorySuggestion,
    clamp_activity_period,
    ConfirmedFact,
    DraftDocument,
    DrilldownDecision,
    FactCandidate,
    InterviewContext,
    JOB_INFO_CATEGORIES,
    JobInfoCandidate,
    JobInfoCategoryQuery,
    JobInfoQueryParams,
    ParagraphDraft,
    PeriodSuggestion,
    LLMUnavailableError,
    RecordExcerpt,
    SentenceWithEvidence,
    SufficiencyResult,
    TEMPERATURE_CREATIVE,
    TEMPERATURE_DETERMINISTIC,
)
from app.services.profile import vocabulary

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=False)

# Ollama가 적용하는 런타임 기본 num_ctx는 모델이 지원하는 컨텍스트(qwen2.5는 32k)가
# 아니라 그보다 훨씬 작아서, 후보 40건짜리 select_relevant_job_info_results 프롬프트는
# 에러 없이 조용히 잘린다. 호출마다 값을 바꾸면 Ollama가 num_ctx별로 런너를 잡아
# 모델을 매번 재적재하므로, 전 호출 공통으로 하나만 고정한다.
_NUM_CTX = 8192

# 생성 호출 전체가 쓰는 타임아웃. 원래 20초였고 한동안 45초였다.
# DGX Spark는 메모리 대역폭(273GB/s)이 decode 벽이라 속도가 모델 크기에 거의
# 반비례한다. 2026-09-10 실측: qwen2.5:72b는 3.0 tok/s로 문단 3개 문서(844토큰)
# 하나에 282초가 걸려 이 상수마저 넘겼고, 그래서 운영 모델을 32b로 내렸다.
# 45초는 어느 모델이든 부족하다.
_GENERATE_TIMEOUT = 240.0

# 응답을 스트리밍으로 받는 이유는 성능이 아니라 Cloudflare다. 무료·Pro·Business
# 플랜의 프록시 read timeout(약 100초)은 **첫 바이트까지의** 시간에 걸리므로,
# stream=False로 72b를 호출하면 생성이 끝나기 전에 524가 뜬다. 조각으로 받으면
# 첫 토큰만 100초 안에 나오면 되고, 총 시간은 위 _GENERATE_TIMEOUT까지 쓸 수 있다.
_STREAM = True

# 43GB짜리 모델을 호출마다 다시 적재하면 그 적재 시간만으로 위의 100초를 넘긴다.
# -1은 "내리지 말고 계속 상주". 서버 쪽 환경변수로도 줄 수 있지만 DGX Spark의
# Ollama는 snap이라 설정 키가 제한적이어서, 요청에 실어 보내는 쪽이 확실하다.
_KEEP_ALIVE = -1

# 2026-09-12: 간헐적 503의 근본 원인은 Spark의 Ollama 러너가 재적재 직후(cold)
# 긴 프롬프트를 받으면 CUDA illegal memory access로 죽는 것이었다(ollama/ollama#17434,
# 운영 devlog 참고). 근본 수정은 Spark에서 해야 하지만(운영 체크리스트), 앱 쪽에서도
# 재시도 1회로 사용자 노출을 없앨 수 있다 — 실측: 관찰된 실패 5건 중 4건이 동일
# 재전송으로 성공했고, 크래시 후 재적재는 11~21초 걸렸다.
_RETRY_DELAY_SECONDS = 4.0


def _render(template_name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)


def _parse_based_on(raw: str | dict, known_excerpts: list[RecordExcerpt]) -> BasedOn:
    """모델이 댄 chunk_id를 프롬프트에 실제로 넣었던 발췌로 되돌린다.

    모델에게는 chunk_id만 받는다. 예전에는 발췌 원문(text)까지 다시 쓰게 했는데,
    decode가 병목인 Spark에서 수백 자를 13 tok/s로 되받아 적는 건 순수한 지연이었고,
    받은 text를 그대로 저장했으니 모델이 발췌를 바꿔 쓰면 원문과 다른 인용이 남았다.
    이제 text/published_at은 항상 우리가 보낸 원문이다. 모르는 chunk_id는 버리고,
    남는 게 없으면 generic_pattern이다 — 근거를 지어낼 수 없다.
    예전 형식(excerpts: [{chunk_id, text, ...}])으로 답해도 chunk_id만 읽는다.
    """
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = {"type": raw}
    if not isinstance(data, dict) or data.get("type") != "record":
        return BasedOn(type="generic_pattern")

    chunk_ids = data.get("chunk_ids")
    if not isinstance(chunk_ids, list):
        chunk_ids = [e.get("chunk_id") for e in data.get("excerpts") or [] if isinstance(e, dict)]
    by_id = {e.chunk_id: e for e in known_excerpts}
    excerpts: list[RecordExcerpt] = []
    for chunk_id in chunk_ids:
        excerpt = by_id.get(chunk_id) if isinstance(chunk_id, str) else None
        if excerpt is not None and excerpt not in excerpts:
            excerpts.append(excerpt)
    if not excerpts:
        return BasedOn(type="generic_pattern")
    return BasedOn(type="record", excerpts=excerpts)


class _TimedOutRequest(LLMUnavailableError):
    """`_generate_once`이 `timeout`을 전부 쓰고 실패했다는 표시.

    `LLMUnavailableError`를 상속하므로 그걸 잡는 기존 호출부(interview.py 등)는
    그대로 503으로 처리한다 — `_generate`의 재시도 로직만 이 타입을 따로 봐서
    건너뛴다(이미 최대 대기 시간을 다 썼으므로 재시도해도 똑같이 실패한다)."""


class LocalOllamaProvider:
    def __init__(self) -> None:
        self._base_url = settings.local_llm_base_url.rstrip("/")
        self._model = settings.local_llm_model_name

    async def extract_facts(
        self, context: InterviewContext, question_text: str, answer_text: str, fact_type_hint: str
    ) -> list[FactCandidate]:
        prompt = _render(
            "interview_extract_facts.jinja",
            category_label=context.category_label,
            gap_start=context.gap_start,
            gap_end=context.gap_end,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
            record_excerpts=context.record_excerpts,
            question_text=question_text,
            answer_text=answer_text,
            fact_type_hint=fact_type_hint,
        )
        response_text = await self._generate(prompt, label="extract_facts", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return [
                FactCandidate(
                    content=f["content"],
                    fact_type=f["fact_type"],
                    based_on=_parse_based_on(f.get("based_on", "generic_pattern"), context.record_excerpts),
                )
                for f in data["facts"]
            ]
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            # The model didn't follow the requested JSON schema — treat this
            # like any other provider failure so the caller can surface it
            # to the next provider instead of a raw 500.
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def followup_question(self, context: InterviewContext) -> str:
        prompt = _render(
            "interview_followup_question.jinja",
            category_label=context.category_label,
            gap_start=context.gap_start,
            gap_end=context.gap_end,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
            record_excerpts=context.record_excerpts,
            asked_questions=context.asked_questions,
            profile_summary=context.profile_summary,
        )
        response_text = await self._generate(prompt, label="followup_question", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            return data["question_text"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def judge_sufficiency(self, context: InterviewContext) -> SufficiencyResult:
        prompt = _render(
            "interview_sufficiency.jinja",
            category_label=context.category_label,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
        )
        response_text = await self._generate(prompt, label="judge_sufficiency", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return SufficiencyResult(sufficient=bool(data["sufficient"]), reason=data.get("reason", ""))
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def judge_drilldown(self, context: InterviewContext) -> DrilldownDecision:
        prompt = _render(
            "interview_drilldown.jinja",
            category_label=context.category_label,
            gap_start=context.gap_start,
            gap_end=context.gap_end,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
            asked_questions=context.asked_questions,
            profile_summary=context.profile_summary,
        )
        response_text = await self._generate(prompt, label="judge_drilldown", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return DrilldownDecision(should_ask=bool(data["should_ask"]), question_text=data.get("question_text"))
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_activity_items(self, category_label: str, answer_text: str) -> list[str]:
        prompt = _render("interview_activity_breakdown.jinja", category_label=category_label, answer_text=answer_text)
        response_text = await self._generate(prompt, label="extract_activity_items", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return [str(item) for item in data["items"]]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        prompt = _render("extract_categories.jinja", free_text=free_text, gap_start=gap_start, gap_end=gap_end)
        response_text = await self._generate(prompt, label="extract_categories", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return [
                CategorySuggestion(
                    category_type=c["category_type"] if c["category_type"] in CATEGORY_TYPES else "other",
                    custom_label=c["custom_label"],
                )
                for c in data["categories"]
            ]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def probe_activity_question(
        self, free_text: str, gap_start: date, gap_end: date, focus: str
    ) -> str:
        prompt = _render(
            "probe_activity_question.jinja",
            free_text=free_text,
            gap_start=gap_start,
            gap_end=gap_end,
            focus=focus,
        )
        # 되묻는 문장이라 매번 똑같으면 기계적으로 읽힌다 — 생성 계열이므로 CREATIVE.
        response_text = await self._generate(prompt, label="probe_activity_question", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            return data["question_text"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None:
        prompt = _render("extract_period.jinja", free_text=free_text, today=today)
        response_text = await self._generate(prompt, label="extract_period", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            if data["start_date"] is None or data["end_date"] is None:
                return None
            start = date.fromisoformat(data["start_date"])
            end = date.fromisoformat(data["end_date"])
            if start > end:
                return None
            return PeriodSuggestion(start_date=start, end_date=end)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_activity_period(
        self, category_label: str, facts: list[ConfirmedFact], gap_start: date, gap_end: date
    ) -> PeriodSuggestion | None:
        prompt = _render(
            "activity_period.jinja",
            category_label=category_label,
            confirmed_facts=facts,
            gap_start=gap_start,
            gap_end=gap_end,
        )
        # temperature는 _generate의 필수 키워드 인자다. 빠져 있던 동안 이 호출은
        # 매번 TypeError를 냈고, 호출부(_maybe_infer_category_period)가 예외를
        # 전부 삼켜서 활동기간 AI 추론이 조용히 죽어 있었다.
        response_text = await self._generate(prompt, label="extract_activity_period", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            if data["start_date"] is None or data["end_date"] is None:
                return None
            start = date.fromisoformat(data["start_date"])
            end = date.fromisoformat(data["end_date"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc
        return clamp_activity_period(start, end, gap_start, gap_end)

    async def generate_document(self, facts: list[ConfirmedFact], tone: str, category_label: str) -> DraftDocument:
        prompt = _render(
            "final_document.jinja",
            confirmed_facts=facts,
            tone=tone,
            category_label=category_label,
        )
        response_text = await self._generate(prompt, label="generate_document", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            # 프롬프트(final_document.jinja)는 사실을 [1]부터 번호 매겨 보여주므로
            # 모델은 1-based 번호로 답한다. LLMProvider 계약(document_generator가
            # facts[i]로 읽는 것)은 0-based라 여기서 한 번만 변환한다. 변환이 없던
            # 동안은 인용이 한 칸씩 밀려 문장이 **다른 사실**을 근거로 저장됐다 —
            # 정직성 가드레일 위반. 번호 0(범위 밖)은 -1이 되어 호출부에서 버려진다.
            paragraphs = [
                ParagraphDraft(
                    topic=p["topic"],
                    sentences=[
                        SentenceWithEvidence(
                            text=s["text"],
                            fact_indices=[
                                i - 1 for i in s["fact_indices"] if isinstance(i, int) and not isinstance(i, bool)
                            ],
                        )
                        for s in p["sentences"]
                    ],
                )
                for p in data["paragraphs"]
            ]
            return DraftDocument(paragraphs=paragraphs)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def classify_job_info_query(self, query: str) -> list[JobInfoCategoryQuery]:
        prompt = _render("classify_job_info_query.jinja", query=query)
        response_text = await self._generate(prompt, label="classify_job_info_query", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return [
                JobInfoCategoryQuery(category=c)
                for c in data["categories"]
                if c in JOB_INFO_CATEGORIES  # hallucinated category name -> drop, don't guess
            ]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_job_info_query_params(self, query: str, known_regions: list[str]) -> JobInfoQueryParams:
        prompt = _render("extract_job_info_query_params.jinja", query=query, known_regions=known_regions)
        response_text = await self._generate(prompt, label="extract_job_info_query_params", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            # 알 수 없는 지역명은 조회 계층에서 걸러지지만, 여기서도 문자열만
            # 남겨 리스트 안에 dict/숫자가 섞여 들어오는 걸 막는다.
            return JobInfoQueryParams(
                regions=[str(r) for r in data.get("regions", []) if isinstance(r, str) and r.strip()],
                keywords=[str(k) for k in data.get("keywords", []) if isinstance(k, str) and k.strip()],
            )
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def select_relevant_job_info_results(
        self, query: str, category_label: str, candidates: list[JobInfoCandidate]
    ) -> list[int]:
        if not candidates:
            return []
        prompt = _render(
            "select_relevant_job_info_results.jinja", query=query, category_label=category_label, candidates=candidates
        )
        response_text = await self._generate(prompt, label="select_relevant_job_info_results", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            valid_indices = {c.index for c in candidates}
            return [i for i in data["relevant_indices"] if i in valid_indices]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def draft_job_info_query_from_facts(self, confirmed_facts: list[ConfirmedFact]) -> str:
        prompt = _render("draft_job_info_query.jinja", confirmed_facts=confirmed_facts)
        response_text = await self._generate(prompt, label="draft_job_info_query_from_facts", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            return str(data.get("draft_query") or "")
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_profile_attributes(
        self, text: str, known: list[str], allow_sensitive: bool
    ) -> list[AttributeCandidate]:
        # allow_sensitive는 프롬프트를 바꾸지 않는다(base.py Protocol 주석 참고).
        prompt = _render(
            "extract_profile_attributes.jinja",
            text=text,
            known=known,
            regions=", ".join(vocabulary.REGION_CHOICES),
            education=", ".join(vocabulary.EDUCATION_CHOICES),
            majors=", ".join(vocabulary.MAJOR_CHOICES),
            employment=", ".join(vocabulary.EMPLOYMENT_CHOICES),
            employment_types=", ".join(vocabulary.EMPLOYMENT_TYPE_CHOICES),
            special=", ".join(vocabulary.SPECIAL_CHOICES),
            marital=", ".join(vocabulary.MARITAL_CHOICES),
        )
        response_text = await self._generate(prompt, label="extract_profile_attributes", timeout=_GENERATE_TIMEOUT, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return [
                AttributeCandidate(
                    key=str(a["key"]),
                    value_label=str(a["value"]).strip(),
                    evidence=str(a.get("evidence") or "").strip(),
                )
                for a in data["attributes"]
                if isinstance(a, dict) and a.get("key") and a.get("value") not in (None, "")
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._base_url}/api/tags", headers=settings.ollama_headers()
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def _generate(self, prompt: str, *, label: str, timeout: float, temperature: float) -> str:
        """`label`은 계측 로그에 찍힐 호출 이름이다(보통 호출한 메서드 이름).

        실패하면 짧게 기다렸다가 **한 번만** 재시도한다 — Spark 크래시 후 재적재
        (11~21초 실측)를 흡수하기 위해서다. 타임아웃으로 실패한 경우는 재시도하지
        않는다: 이미 `timeout`을 다 써서 실패한 것이므로 다시 걸어도 똑같이 그만큼
        기다리다 또 실패할 뿐이다(`_TimedOutRequest`로 구분해서 건너뛴다).
        """
        try:
            return await self._generate_once(prompt, label=label, timeout=timeout, temperature=temperature)
        except _TimedOutRequest:
            raise
        except LLMUnavailableError:
            await asyncio.sleep(_RETRY_DELAY_SECONDS)
            return await self._generate_once(prompt, label=label, timeout=timeout, temperature=temperature)

    async def _generate_once(self, prompt: str, *, label: str, timeout: float, temperature: float) -> str:
        # /api/chat은 system 메시지 분리를 지원해 JSON 스키마 준수율이 높다
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an assistant that helps reconstruct career gap period narratives. "
                        "Always respond in Korean. Output JSON only — no other text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": _STREAM,
            "format": "json",
            "keep_alive": _KEEP_ALIVE,
            "options": {"temperature": temperature, "num_ctx": _NUM_CTX},
        }
        if settings.local_llm_disable_thinking:
            payload["think"] = False
        started = time.monotonic()
        try:
            # 같은 Ollama 러너를 우리 쪽 요청끼리 겹치지 않게 한다 — 겹치면 크래시
            # 한 번이 여러 요청을 한꺼번에 죽인다(ollama_gate.py 모듈독스트링 참고).
            async with OLLAMA_GATE:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{self._base_url}/api/chat",
                        json=payload,
                        headers=settings.ollama_headers(),
                    ) as resp:
                        if resp.status_code >= 400:
                            # 스트리밍 응답은 본문을 읽기 전에 .text에 접근할 수 없다.
                            # 아래 HTTPStatusError 핸들러가 본문 preview를 쓰므로 먼저 읽는다.
                            await resp.aread()
                        resp.raise_for_status()
                        content, stats = await self._collect_stream(resp)
                        _log_generation_stats(label, self._model, time.monotonic() - started, stats)
                        return content
        except LLMUnavailableError:
            raise
        except httpx.TimeoutException as exc:
            raise _TimedOutRequest("Ollama request timed out") from exc
        except httpx.HTTPStatusError as exc:
            # The bare status code alone doesn't say who returned it — a
            # Cloudflare edge block (bot/WAF) and Ollama's own rejection both
            # surface as an httpx.HTTPStatusError with no further detail in
            # str(exc). Cloudflare's block pages are text/html with a CF-RAY
            # header and distinctive copy ("Attention Required", "cf-error-code");
            # Ollama's own errors are small JSON. Logging both here was the
            # missing piece while chasing the 2026-09-04 403 on production.
            body_preview = exc.response.text[:300] if exc.response is not None else ""
            cf_ray = exc.response.headers.get("cf-ray") if exc.response is not None else None
            raise LLMUnavailableError(
                f"Ollama unavailable: {exc} | content-type={exc.response.headers.get('content-type') if exc.response is not None else None} "
                f"cf-ray={cf_ray} body={body_preview!r}"
            ) from exc
        except Exception as exc:
            raise LLMUnavailableError(f"Ollama unavailable: {exc}") from exc

    @staticmethod
    async def _collect_stream(resp: httpx.Response) -> tuple[str, dict]:
        """Ollama의 NDJSON 스트림을 하나의 content 문자열로 이어붙인다.

        stream=true면 `{"message":{"content":"..."},"done":false}` 형태의 JSON이
        한 줄씩 내려오고 마지막 줄에 `done:true`가 온다. 호출부는 예전과 똑같이
        완성된 JSON 문자열 하나만 받는다 — 스트리밍은 Cloudflare의 100초 벽을
        넘기 위한 전송 방식이지, 인터페이스 변경이 아니다.

        두 번째 값은 마지막 줄(done:true) 그 자체다. 거기에만 eval_count(출력
        토큰 수)·eval_duration 같은 서버 측 계측이 실린다.
        """
        parts: list[str] = []
        final: dict = {}
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            # Ollama는 스트림 중간에도 error 필드로 실패를 알린다(예: 모델 없음).
            # 이때 HTTP 상태는 이미 200으로 나가 있어서 raise_for_status로는 못 잡는다.
            if chunk.get("error"):
                raise LLMUnavailableError(f"Ollama returned an error: {chunk['error']}")
            parts.append(chunk.get("message", {}).get("content", ""))
            if chunk.get("done"):
                final = chunk
                break
        return "".join(parts), final


def _log_generation_stats(label: str, model: str, wall_seconds: float, stats: dict) -> None:
    """호출 한 건의 속도를 한 줄로 남긴다.

    Spark에서 응답 시간은 거의 출력 토큰 수 ÷ decode 속도로 정해진다. 그래서
    프롬프트를 줄였는지, 모델을 바꿨는지의 효과는 이 줄의 out_tokens와 tok/s로
    바로 보인다. wall은 Render에서 잰 전체 시간(터널 왕복 포함)이고, 나머지는
    Ollama가 스스로 잰 값이다(ns). 계측이 빠진 응답이어도 호출은 실패시키지 않는다.
    """
    def _seconds(key: str) -> float:
        return (stats.get(key) or 0) / 1e9

    out_tokens = stats.get("eval_count") or 0
    decode_s = _seconds("eval_duration")
    logger.info(
        "llm %s model=%s wall=%.1fs load=%.1fs prefill=%dtok/%.1fs out=%dtok/%.1fs (%.1f tok/s)",
        label,
        model,
        wall_seconds,
        _seconds("load_duration"),
        stats.get("prompt_eval_count") or 0,
        _seconds("prompt_eval_duration"),
        out_tokens,
        decode_s,
        out_tokens / decode_s if decode_s else 0.0,
    )
