from __future__ import annotations

import json
from pathlib import Path

from google import genai
from google.genai import types
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.services.llm.base import (
    BasedOn,
    ConfirmedFact,
    DraftDocument,
    InterviewContext,
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
        self._client = genai.Client(api_key=settings.gemini_api_key)

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
        data = json.loads(text)
        based_on_raw = data.get("based_on", "generic_pattern")
        if isinstance(based_on_raw, str):
            based_on = BasedOn(type=based_on_raw)
        else:
            based_on = BasedOn(type=based_on_raw.get("type", "generic_pattern"))
        return Suggestion(draft_text=data["draft_text"], based_on=based_on)

    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument:
        category_label = facts[0].fact_type if facts else ""
        prompt = _render(
            "final_document.jinja",
            confirmed_facts=facts,
            tone=tone,
            category_label=category_label,
        )
        text = await self._call(prompt)
        data = json.loads(text)
        sentences = [
            SentenceWithEvidence(text=s["text"], fact_indices=s["fact_indices"])
            for s in data["sentences"]
        ]
        return DraftDocument(sentences=sentences)

    async def health_check(self) -> bool:
        return bool(settings.gemini_api_key)

    async def _call(self, prompt: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            return response.text
        except Exception as exc:
            raise ProviderUnavailableError(f"Gemini unavailable: {exc}") from exc
