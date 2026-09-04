from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.llm.fallback import _build_providers
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.local_ollama import LocalOllamaProvider


def _set_order(monkeypatch, value: str) -> None:
    monkeypatch.setattr(settings, "llm_provider_order", value)


def test_build_providers_is_case_insensitive(monkeypatch):
    # A differently-cased LLM_PROVIDER_ORDER (e.g. "Local,Gemini") used to
    # silently produce an empty provider list — every LLM call would then
    # fail instantly with AllProvidersFailedError and no per-provider
    # failure logging at all, since FallbackProvider's fallback loop never
    # runs on an empty list (production incident, 2026-09-04).
    _set_order(monkeypatch, "Local,Gemini")
    providers = _build_providers()
    assert [type(p) for p in providers] == [LocalOllamaProvider, GeminiProvider]


def test_build_providers_ignores_blank_entries(monkeypatch):
    _set_order(monkeypatch, "local, gemini,")
    providers = _build_providers()
    assert [type(p) for p in providers] == [LocalOllamaProvider, GeminiProvider]


def test_build_providers_empty_order_returns_empty_list(monkeypatch):
    _set_order(monkeypatch, "")
    assert _build_providers() == []
