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
    InterviewContext,
    ProviderUnavailableError,
    RecordExcerpt,
    SentenceWithEvidence,
    Suggestion,
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

    async def draft_suggestion(self, context: InterviewContext, step: str) -> Suggestion:
        prompt = _render(
            "draft_suggestion.jinja",
            category_label=context.category_label,
            gap_period=context,
            confirmed_facts_so_far=context.confirmed_facts_so_far,
            record_excerpts=context.record_excerpts,
            step_label=step,
        )
        response_text = await self._generate(prompt, timeout=20.0)
        try:
            data = json.loads(response_text)
            return Suggestion(
                draft_text=data["draft_text"],
                based_on=_parse_based_on(data.get("based_on", "generic_pattern")),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            # The model didn't follow the requested JSON schema — treat this
            # like any other provider failure so FallbackProvider moves on
            # to the next provider instead of a raw 500.
            raise ProviderUnavailableError(f"Ollama returned malformed response: {exc}") from exc

    async def extract_categories(
        self, free_text: str, gap_start: date, gap_end: date
    ) -> list[CategorySuggestion]:
        prompt = _render("extract_categories.jinja", free_text=free_text, gap_start=gap_start, gap_end=gap_end)
        response_text = await self._generate(prompt, timeout=20.0)
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

    async def generate_document(self, facts: list[ConfirmedFact], tone: str) -> DraftDocument:
        category_label = facts[0].fact_type if facts else ""
        prompt = _render(
            "final_document.jinja",
            confirmed_facts=facts,
            tone=tone,
            category_label=category_label,
        )
        response_text = await self._generate(prompt, timeout=20.0)
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
        except Exception as exc:
            raise ProviderUnavailableError(f"Ollama unavailable: {exc}") from exc
