from __future__ import annotations

import json

import pytest

from app.services.llm import local_ollama
from app.services.llm.base import JobInfoCandidate, ProviderUnavailableError
from app.services.llm.local_ollama import LocalOllamaProvider

CANDIDATES = [
    JobInfoCandidate(index=0, title="자바 웹 개발자 양성과정", subtitle="국민내일배움카드 · 고양시"),
    JobInfoCandidate(index=1, title="조리기능사 취득과정", subtitle="국민내일배움카드 · 의정부시"),
    JobInfoCandidate(index=2, title="클라우드 서버 운영 과정", subtitle="사업주훈련 · 파주시"),
]


class _StubResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"content": self._content}}


@pytest.fixture
def ollama_calls(monkeypatch):
    """Ollama에 실제로 보낸 요청 본문을 기록한다.

    FakeLLMProvider(tests/api/conftest.py)는 프로바이더 전체를 대체해서
    프롬프트 렌더링·JSON 파싱·요청 본문 구성을 하나도 지나가지 않는다.
    여기서는 그 아래층(httpx)만 갈아끼워 실제 payload를 검사한다.
    """
    calls: list[dict] = []
    canned = {"content": "{}"}

    class _StubClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_StubClient":
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def post(self, url: str, json: dict) -> _StubResponse:  # noqa: A002 - httpx의 인자명
            calls.append(json)
            return _StubResponse(canned["content"])

    monkeypatch.setattr(local_ollama.httpx, "AsyncClient", _StubClient)
    return calls, canned


@pytest.mark.asyncio
async def test_judgment_calls_use_deterministic_temperature(ollama_calls):
    calls, canned = ollama_calls
    canned["content"] = json.dumps({"categories": ["training_course"]})
    await LocalOllamaProvider().classify_job_info_query("경기 북부 훈련과정 있어?")

    canned["content"] = json.dumps({"relevant_indices": [0]})
    await LocalOllamaProvider().select_relevant_job_info_results("질문", "직업훈련과정", CANDIDATES)

    assert [c["options"]["temperature"] for c in calls] == [0.0, 0.0]


@pytest.mark.asyncio
async def test_generative_calls_use_creative_temperature(ollama_calls):
    calls, canned = ollama_calls
    canned["content"] = json.dumps({"draft_query": "카페 알바 경험 살릴 훈련과정"})
    await LocalOllamaProvider().draft_job_info_query_from_facts([])

    assert calls[0]["options"]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_every_call_sets_num_ctx(ollama_calls):
    # num_ctx를 안 넘기면 Ollama 기본값이 걸려 후보 40건 프롬프트가 조용히 잘린다.
    calls, canned = ollama_calls
    canned["content"] = json.dumps({"items": ["카페 아르바이트"]})
    await LocalOllamaProvider().extract_activity_items("아르바이트", "카페에서 일했어요")

    assert calls[0]["options"]["num_ctx"] == 8192


@pytest.mark.asyncio
async def test_select_relevant_drops_hallucinated_indices(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = json.dumps({"relevant_indices": [0, 7, -1, 2]})

    result = await LocalOllamaProvider().select_relevant_job_info_results("질문", "직업훈련과정", CANDIDATES)

    assert result == [0, 2]


@pytest.mark.asyncio
async def test_select_relevant_with_no_candidates_never_calls_the_model(ollama_calls):
    calls, _ = ollama_calls

    result = await LocalOllamaProvider().select_relevant_job_info_results("질문", "직업훈련과정", [])

    assert result == []
    assert calls == []


@pytest.mark.asyncio
async def test_select_relevant_malformed_json_raises_provider_unavailable(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = "관련 있는 건 0번입니다"

    with pytest.raises(ProviderUnavailableError):
        await LocalOllamaProvider().select_relevant_job_info_results("질문", "직업훈련과정", CANDIDATES)


@pytest.mark.asyncio
async def test_select_relevant_non_iterable_indices_raises_provider_unavailable(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = json.dumps({"relevant_indices": 5})

    with pytest.raises(ProviderUnavailableError):
        await LocalOllamaProvider().select_relevant_job_info_results("질문", "직업훈련과정", CANDIDATES)


@pytest.mark.asyncio
async def test_classify_drops_hallucinated_category_names(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = json.dumps({"categories": ["training_course", "job_board", "잡페어"]})

    result = await LocalOllamaProvider().classify_job_info_query("훈련과정 있어?")

    assert [q.category for q in result] == ["training_course"]
