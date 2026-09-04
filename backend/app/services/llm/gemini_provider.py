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
    InterviewContext,
    PeriodSuggestion,
    ProviderUnavailableError,
    SentenceWithEvidence,
    Suggestion,
)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=False)


def _render(template_name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)


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

    async def draft_suggestion(self, context: InterviewContext, step: str) -> Suggestion:
        prompt = _render(
            "draft_suggestion.jinja",
            category_label=context.category_label,
            gap_period=context,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
            record_excerpts=context.record_excerpts,
            step_label=step,
        )
        text = await self._call(prompt)
        try:
            data = json.loads(text)
            based_on_raw = data.get("based_on", "generic_pattern")
            if isinstance(based_on_raw, str):
                based_on = BasedOn(type=based_on_raw)
            else:
                based_on = BasedOn(type=based_on_raw.get("type", "generic_pattern"))
            return Suggestion(draft_text=data["draft_text"], based_on=based_on)
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        prompt = _render("extract_categories.jinja", free_text=free_text, gap_start=gap_start, gap_end=gap_end)
        text = await self._call(prompt)
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
        text = await self._call(prompt)
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

    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument:
        category_label = facts[0].fact_type if facts else ""
        prompt = _render(
            "final_document.jinja",
            confirmed_facts=facts,
            tone=tone,
            category_label=category_label,
        )
        text = await self._call(prompt)
        try:
            data = json.loads(text)
            sentences = [
                SentenceWithEvidence(text=s["text"], fact_indices=s["fact_indices"])
                for s in data["sentences"]
            ]
            return DraftDocument(sentences=sentences)
        except (json.JSONDecodeError, KeyError) as exc:
            raise ProviderUnavailableError(f"Gemini returned malformed response: {exc}") from exc

    async def health_check(self) -> bool:
        return bool(settings.gemini_api_key)

    async def _call(self, prompt: str) -> str:
        try:
            client = self._ensure_client()
            response = await client.aio.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            return response.text
        except Exception as exc:
            raise ProviderUnavailableError(f"Gemini unavailable: {exc}") from exc
