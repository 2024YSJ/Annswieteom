from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.models.activity_category import CATEGORY_TYPES
from app.services.llm.base import (
    AllProvidersFailedError,
    BasedOn,
    CategorySuggestion,
    ConfirmedFact,
    DraftDocument,
    FactCandidate,
    InterviewContext,
    PeriodSuggestion,
    ProviderUnavailableError,
    RecordExcerpt,
    SentenceWithEvidence,
    SufficiencyResult,
)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=False)


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
        response_text = await self._generate(prompt, timeout=45.0)
        try:
            data = json.loads(response_text)
            return data["draft_answer"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

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
        response_text = await self._generate(prompt, timeout=45.0)
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
            # like any other provider failure so FallbackProvider moves on
            # to the next provider instead of a raw 500.
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

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
        response_text = await self._generate(prompt, timeout=45.0)
        try:
            data = json.loads(response_text)
            return data["question_text"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def judge_sufficiency(self, context: InterviewContext) -> SufficiencyResult:
        prompt = _render(
            "interview_sufficiency.jinja",
            category_label=context.category_label,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
        )
        response_text = await self._generate(prompt, timeout=45.0)
        try:
            data = json.loads(response_text)
            return SufficiencyResult(sufficient=bool(data["sufficient"]), reason=data.get("reason", ""))
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        prompt = _render("extract_categories.jinja", free_text=free_text, gap_start=gap_start, gap_end=gap_end)
        response_text = await self._generate(prompt, timeout=45.0)
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
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_period(self, free_text: str, today: date) -> PeriodSuggestion | None:
        prompt = _render("extract_period.jinja", free_text=free_text, today=today)
        response_text = await self._generate(prompt, timeout=45.0)
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
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument:
        category_label = facts[0].fact_type if facts else ""
        prompt = _render(
            "final_document.jinja",
            confirmed_facts=facts,
            tone=tone,
            category_label=category_label,
        )
        response_text = await self._generate(prompt, timeout=45.0)
        try:
            data = json.loads(response_text)
            sentences = [
                SentenceWithEvidence(text=s["text"], fact_indices=s["fact_indices"])
                for s in data["sentences"]
            ]
            return DraftDocument(sentences=sentences)
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def _generate(self, prompt: str, timeout: float) -> str:
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
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        except httpx.TimeoutException as exc:
            raise TimeoutError("Ollama request timed out") from exc
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
            raise ProviderUnavailableError(
                f"Ollama unavailable: {exc} | content-type={exc.response.headers.get('content-type') if exc.response is not None else None} "
                f"cf-ray={cf_ray} body={body_preview!r}"
            ) from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Ollama unavailable: {exc}") from exc
