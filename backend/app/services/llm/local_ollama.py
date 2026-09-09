from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.models.activity_category import CATEGORY_TYPES
from app.services.llm.base import (
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

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=False)

# Ollama가 적용하는 런타임 기본 num_ctx는 모델이 지원하는 컨텍스트(qwen2.5는 32k)가
# 아니라 그보다 훨씬 작아서, 후보 40건짜리 select_relevant_job_info_results 프롬프트는
# 에러 없이 조용히 잘린다. 호출마다 값을 바꾸면 Ollama가 num_ctx별로 런너를 잡아
# 모델을 매번 재적재하므로, 전 호출 공통으로 하나만 고정한다.
_NUM_CTX = 8192


def _render(template_name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)


def _parse_based_on(raw: str | dict) -> BasedOn:
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = {"type": raw}

    if data.get("type") == "record":
        excerpts = [
            RecordExcerpt(
                chunk_id=e.get("chunk_id", ""),
                text=e.get("text", ""),
                published_at=e.get("published_at"),
            )
            for e in data.get("excerpts", [])
        ]
        return BasedOn(type="record", excerpts=excerpts)
    return BasedOn(type="generic_pattern")


class LocalOllamaProvider:
    def __init__(self) -> None:
        self._base_url = settings.local_llm_base_url.rstrip("/")
        self._model = settings.local_llm_model_name

    async def draft_answer(self, context: InterviewContext, question_text: str) -> str:
        prompt = _render(
            "interview_draft_answer.jinja",
            category_label=context.category_label,
            gap_start=context.gap_start,
            gap_end=context.gap_end,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
            record_excerpts=context.record_excerpts,
            question_text=question_text,
        )
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            return data["draft_answer"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

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
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return [
                FactCandidate(
                    content=f["content"],
                    fact_type=f["fact_type"],
                    based_on=_parse_based_on(f.get("based_on", "generic_pattern")),
                )
                for f in data["facts"]
            ]
        except (json.JSONDecodeError, KeyError) as exc:
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
        )
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_CREATIVE)
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
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
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
        )
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return DrilldownDecision(should_ask=bool(data["should_ask"]), question_text=data.get("question_text"))
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_activity_items(self, category_label: str, answer_text: str) -> list[str]:
        prompt = _render("interview_activity_breakdown.jinja", category_label=category_label, answer_text=answer_text)
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            return [str(item) for item in data["items"]]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        prompt = _render("extract_categories.jinja", free_text=free_text, gap_start=gap_start, gap_end=gap_end)
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
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
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            return data["question_text"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None:
        prompt = _render("extract_period.jinja", free_text=free_text, today=today)
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
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
        response_text = await self._generate(prompt, timeout=45.0)
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
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            paragraphs = [
                ParagraphDraft(
                    topic=p["topic"],
                    sentences=[SentenceWithEvidence(text=s["text"], fact_indices=s["fact_indices"]) for s in p["sentences"]],
                )
                for p in data["paragraphs"]
            ]
            return DraftDocument(paragraphs=paragraphs)
        except (json.JSONDecodeError, KeyError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def classify_job_info_query(self, query: str) -> list[JobInfoCategoryQuery]:
        prompt = _render("classify_job_info_query.jinja", query=query)
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
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
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
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
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(response_text)
            valid_indices = {c.index for c in candidates}
            return [i for i in data["relevant_indices"] if i in valid_indices]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def draft_job_info_query_from_facts(self, confirmed_facts: list[ConfirmedFact]) -> str:
        prompt = _render("draft_job_info_query.jinja", confirmed_facts=confirmed_facts)
        response_text = await self._generate(prompt, timeout=45.0, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(response_text)
            return str(data.get("draft_query") or "")
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def _generate(self, prompt: str, timeout: float, *, temperature: float) -> str:
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
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_ctx": _NUM_CTX},
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError("Ollama request timed out") from exc
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
