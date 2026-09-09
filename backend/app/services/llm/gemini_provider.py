from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from google import genai
from google.genai import types
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.models.activity_category import CATEGORY_TYPES
from app.services.llm.base import (
    BasedOn,
    CategorySuggestion,
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
    ProviderUnavailableError,
    RecordExcerpt,
    SentenceWithEvidence,
    SufficiencyResult,
    TEMPERATURE_CREATIVE,
    TEMPERATURE_DETERMINISTIC,
)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=False)


def _render(template_name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)


def _parse_based_on(raw: str | dict) -> BasedOn:
    if not isinstance(raw, dict):
        return BasedOn(type=str(raw))
    if raw.get("type") == "record":
        excerpts = [
            RecordExcerpt(
                chunk_id=e.get("chunk_id", ""),
                text=e.get("text", ""),
                published_at=e.get("published_at"),
            )
            for e in raw.get("excerpts", [])
        ]
        return BasedOn(type="record", excerpts=excerpts)
    return BasedOn(type="generic_pattern")


class GeminiProvider:
    def __init__(self) -> None:
        # Lazy — genai.Client(api_key="") raises ValueError synchronously, and
        # FallbackProvider._build_providers() constructs every configured
        # provider eagerly regardless of LLM_PROVIDER_ORDER. Raising here would
        # escape this class's own error handling entirely (it happens during
        # FastAPI dependency resolution, before any endpoint's try/except runs)
        # and surface to the browser as a bare 500 with no CORS headers,
        # instead of the clean "try the next provider" behavior every other
        # failure mode gets. Deferring construction to _call() lets the
        # existing try/except there convert it to ProviderUnavailableError
        # like any other Gemini failure.
        self._client: genai.Client | None = None

    def _ensure_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

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
        text = await self._call(prompt, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(text)
            return data["draft_answer"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

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
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            return [
                FactCandidate(
                    content=f["content"],
                    fact_type=f["fact_type"],
                    based_on=_parse_based_on(f.get("based_on", "generic_pattern")),
                )
                for f in data["facts"]
            ]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

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
        text = await self._call(prompt, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(text)
            return data["question_text"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def judge_sufficiency(self, context: InterviewContext) -> SufficiencyResult:
        prompt = _render(
            "interview_sufficiency.jinja",
            category_label=context.category_label,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
        )
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            return SufficiencyResult(sufficient=bool(data["sufficient"]), reason=data.get("reason", ""))
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def judge_drilldown(self, context: InterviewContext) -> DrilldownDecision:
        prompt = _render(
            "interview_drilldown.jinja",
            category_label=context.category_label,
            gap_start=context.gap_start,
            gap_end=context.gap_end,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
            asked_questions=context.asked_questions,
        )
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            return DrilldownDecision(should_ask=bool(data["should_ask"]), question_text=data.get("question_text"))
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def extract_activity_items(self, category_label: str, answer_text: str) -> list[str]:
        prompt = _render("interview_activity_breakdown.jinja", category_label=category_label, answer_text=answer_text)
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            return [str(item) for item in data["items"]]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        prompt = _render("extract_categories.jinja", free_text=free_text, gap_start=gap_start, gap_end=gap_end)
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            return [
                CategorySuggestion(
                    category_type=c["category_type"] if c["category_type"] in CATEGORY_TYPES else "other",
                    custom_label=c["custom_label"],
                )
                for c in data["categories"]
            ]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None:
        prompt = _render("extract_period.jinja", free_text=free_text, today=today)
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            if data["start_date"] is None or data["end_date"] is None:
                return None
            start = date.fromisoformat(data["start_date"])
            end = date.fromisoformat(data["end_date"])
            if start > end:
                return None
            return PeriodSuggestion(start_date=start, end_date=end)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def generate_document(self, facts: list[ConfirmedFact], tone: str, category_label: str) -> DraftDocument:
        prompt = _render(
            "final_document.jinja",
            confirmed_facts=facts,
            tone=tone,
            category_label=category_label,
        )
        text = await self._call(prompt, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(text)
            paragraphs = [
                ParagraphDraft(
                    topic=p["topic"],
                    sentences=[SentenceWithEvidence(text=s["text"], fact_indices=s["fact_indices"]) for s in p["sentences"]],
                )
                for p in data["paragraphs"]
            ]
            return DraftDocument(paragraphs=paragraphs)
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def classify_job_info_query(self, query: str) -> list[JobInfoCategoryQuery]:
        prompt = _render("classify_job_info_query.jinja", query=query)
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            return [JobInfoCategoryQuery(category=c) for c in data["categories"] if c in JOB_INFO_CATEGORIES]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def extract_job_info_query_params(self, query: str, known_regions: list[str]) -> JobInfoQueryParams:
        prompt = _render("extract_job_info_query_params.jinja", query=query, known_regions=known_regions)
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            return JobInfoQueryParams(
                regions=[str(r) for r in data.get("regions", []) if isinstance(r, str) and r.strip()],
                keywords=[str(k) for k in data.get("keywords", []) if isinstance(k, str) and k.strip()],
            )
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def select_relevant_job_info_results(
        self, query: str, category_label: str, candidates: list[JobInfoCandidate]
    ) -> list[int]:
        if not candidates:
            return []
        prompt = _render(
            "select_relevant_job_info_results.jinja", query=query, category_label=category_label, candidates=candidates
        )
        text = await self._call(prompt, temperature=TEMPERATURE_DETERMINISTIC)
        try:
            data = json.loads(text)
            valid_indices = {c.index for c in candidates}
            return [i for i in data["relevant_indices"] if i in valid_indices]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def draft_job_info_query_from_facts(self, confirmed_facts: list[ConfirmedFact]) -> str:
        prompt = _render("draft_job_info_query.jinja", confirmed_facts=confirmed_facts)
        text = await self._call(prompt, temperature=TEMPERATURE_CREATIVE)
        try:
            data = json.loads(text)
            return str(data.get("draft_query") or "")
        except json.JSONDecodeError as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def health_check(self) -> bool:
        return bool(settings.gemini_api_key)

    async def _call(self, prompt: str, *, temperature: float) -> str:
        try:
            client = self._ensure_client()
            response = await client.aio.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
            return response.text
        except Exception as exc:
            raise ProviderUnavailableError(f"Gemini unavailable: {exc}") from exc
