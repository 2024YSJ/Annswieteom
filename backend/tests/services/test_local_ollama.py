from __future__ import annotations

import json

import pytest

from app.services.llm import local_ollama
from app.services.llm.base import JobInfoCandidate, LLMUnavailableError
from app.services.llm.local_ollama import LocalOllamaProvider

CANDIDATES = [
    JobInfoCandidate(index=0, title="자바 웹 개발자 양성과정", subtitle="국민내일배움카드 · 고양시"),
    JobInfoCandidate(index=1, title="조리기능사 취득과정", subtitle="국민내일배움카드 · 의정부시"),
    JobInfoCandidate(index=2, title="클라우드 서버 운영 과정", subtitle="사업주훈련 · 파주시"),
]


class _StubStreamResponse:
    """Ollama의 stream=true 응답 흉내.

    실제 Ollama는 `{"message":{"content":"..."},"done":false}` NDJSON을 한 줄씩
    내려보내고 마지막 줄에 done:true를 붙인다. 여기서는 content를 두 조각으로
    쪼개 내려보내 어댑터가 정말로 이어붙이는지(한 조각만 쓰지 않는지) 확인한다.
    """

    def __init__(self, content: str, status_code: int = 200) -> None:
        self._content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"stub was given status {self.status_code}")

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        half = len(self._content) // 2
        yield json.dumps({"message": {"content": self._content[:half]}, "done": False})
        yield ""  # 빈 줄이 섞여 와도 건너뛰어야 한다
        yield json.dumps({"message": {"content": self._content[half:]}, "done": True})


@pytest.fixture
def ollama_calls(monkeypatch):
    """Ollama에 실제로 보낸 요청 본문을 기록한다.

    FakeLLMProvider(tests/api/conftest.py)는 프로바이더 전체를 대체해서
    프롬프트 렌더링·JSON 파싱·요청 본문 구성을 하나도 지나가지 않는다.
    여기서는 그 아래층(httpx)만 갈아끼워 실제 payload를 검사한다.
    """
    calls: list[dict] = []
    # sent_headers는 canned에 얹었다 — 기존 12개 테스트가 (calls, canned) 2-튜플로
    # 언패킹하고 있어서 반환 형태를 바꾸면 전부 손봐야 한다.
    canned: dict = {"content": "{}", "sent_headers": []}

    class _StubStreamCtx:
        def __init__(self, response: _StubStreamResponse) -> None:
            self._response = response

        async def __aenter__(self) -> _StubStreamResponse:
            return self._response

        async def __aexit__(self, *exc_info) -> None:
            return None

    class _StubClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_StubClient":
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        def stream(self, method: str, url: str, json: dict, headers: dict | None = None):  # noqa: A002 - httpx의 인자명
            assert method == "POST"
            calls.append(json)
            canned["sent_headers"].append(headers)
            return _StubStreamCtx(_StubStreamResponse(canned["content"]))

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

    with pytest.raises(LLMUnavailableError):
        await LocalOllamaProvider().select_relevant_job_info_results("질문", "직업훈련과정", CANDIDATES)


@pytest.mark.asyncio
async def test_select_relevant_non_iterable_indices_raises_provider_unavailable(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = json.dumps({"relevant_indices": 5})

    with pytest.raises(LLMUnavailableError):
        await LocalOllamaProvider().select_relevant_job_info_results("질문", "직업훈련과정", CANDIDATES)


@pytest.mark.asyncio
async def test_extract_query_params_keeps_only_strings(ollama_calls):
    # 리스트 안에 dict/숫자가 섞여 오면 지역 변환에서 터지므로 여기서 걸러낸다.
    _, canned = ollama_calls
    canned["content"] = json.dumps(
        {"regions": ["경기 북부", "", 41, {"name": "서울"}], "keywords": ["자바", None, "웹 개발"]}
    )

    params = await LocalOllamaProvider().extract_job_info_query_params("질문", ["경기 북부", "서울"])

    assert params.regions == ["경기 북부"]
    assert params.keywords == ["자바", "웹 개발"]


@pytest.mark.asyncio
async def test_extract_query_params_tolerates_missing_keys(ollama_calls):
    # 조건이 없는 질문("요즘 공채 뜬 거 있어?")이면 키가 아예 빠져 올 수 있다 —
    # 그건 실패가 아니라 "조건 없음"이라 조건 없이 조회하면 된다.
    _, canned = ollama_calls
    canned["content"] = json.dumps({})

    params = await LocalOllamaProvider().extract_job_info_query_params("질문", [])

    assert params.regions == []
    assert params.keywords == []


@pytest.mark.asyncio
async def test_extract_query_params_uses_deterministic_temperature(ollama_calls):
    calls, canned = ollama_calls
    canned["content"] = json.dumps({"regions": [], "keywords": []})

    await LocalOllamaProvider().extract_job_info_query_params("질문", [])

    assert calls[0]["options"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_extract_query_params_malformed_json_raises_provider_unavailable(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = "경기 북부에서 자바 과정을 찾으시는군요"

    with pytest.raises(LLMUnavailableError):
        await LocalOllamaProvider().extract_job_info_query_params("질문", [])


@pytest.mark.asyncio
async def test_classify_drops_hallucinated_category_names(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = json.dumps({"categories": ["training_course", "job_board", "잡페어"]})

    result = await LocalOllamaProvider().classify_job_info_query("훈련과정 있어?")

    assert [q.category for q in result] == ["training_course"]


@pytest.mark.asyncio
async def test_access_headers_are_sent_when_the_token_is_configured(ollama_calls, monkeypatch):
    # 터널이 Cloudflare Access 뒤에 있어서 이 헤더가 없으면 전부 403이 된다.
    monkeypatch.setattr(local_ollama.settings, "llm_access_client_id", "id.access", raising=False)
    monkeypatch.setattr(local_ollama.settings, "llm_access_client_secret", "secret", raising=False)
    _, canned = ollama_calls
    canned["content"] = json.dumps({"categories": ["training_course"]})

    await LocalOllamaProvider().classify_job_info_query("훈련과정 있어?")

    assert canned["sent_headers"][0] == {
        "CF-Access-Client-Id": "id.access",
        "CF-Access-Client-Secret": "secret",
    }


@pytest.mark.asyncio
async def test_no_access_headers_when_the_token_is_unset(ollama_calls, monkeypatch):
    # 로컬 dev(localhost:11434)는 Access 뒤에 없다. 빈 값이 정상 상태여야 한다.
    monkeypatch.setattr(local_ollama.settings, "llm_access_client_id", "", raising=False)
    monkeypatch.setattr(local_ollama.settings, "llm_access_client_secret", "", raising=False)
    _, canned = ollama_calls
    canned["content"] = json.dumps({"categories": ["training_course"]})

    await LocalOllamaProvider().classify_job_info_query("훈련과정 있어?")

    assert canned["sent_headers"][0] == {}


@pytest.mark.asyncio
async def test_half_configured_access_token_sends_no_headers(ollama_calls, monkeypatch):
    # id만 있고 secret이 없으면 Access는 어차피 거절한다. 반쪽 헤더를 보내
    # 403 원인을 헷갈리게 만들지 말고 아무것도 안 보낸다.
    monkeypatch.setattr(local_ollama.settings, "llm_access_client_id", "id.access", raising=False)
    monkeypatch.setattr(local_ollama.settings, "llm_access_client_secret", "", raising=False)
    _, canned = ollama_calls
    canned["content"] = json.dumps({"categories": ["training_course"]})

    await LocalOllamaProvider().classify_job_info_query("훈련과정 있어?")

    assert canned["sent_headers"][0] == {}


@pytest.mark.asyncio
async def test_generation_is_streamed_and_reassembled(ollama_calls):
    # 스트리밍은 성능이 아니라 Cloudflare 때문이다 — 무료 플랜의 프록시 read
    # timeout(약 100초)은 첫 바이트까지의 시간에 걸리고, 72b는 stream=False로는
    # 문서 생성을 그 안에 끝내지 못해 524가 뜬다. 그러니 stream 플래그가 꺼지면
    # 프로덕션이 조용히 524로 돌아간다.
    calls, canned = ollama_calls
    canned["content"] = json.dumps({"items": ["카페 아르바이트", "재고 관리"]}, ensure_ascii=False)

    items = await LocalOllamaProvider().extract_activity_items("아르바이트", "카페에서 일했어요")

    assert calls[0]["stream"] is True
    # 조각을 하나만 쓰지 않고 전부 이어붙였는지 — 이어붙이지 않으면 JSON이 깨진다
    assert items == ["카페 아르바이트", "재고 관리"]


@pytest.mark.asyncio
async def test_every_call_pins_keep_alive(ollama_calls):
    # 43GB 모델을 호출마다 재적재하면 그 시간만으로 첫 바이트가 100초를 넘긴다.
    calls, canned = ollama_calls
    canned["content"] = json.dumps({"items": []})

    await LocalOllamaProvider().extract_activity_items("아르바이트", "카페에서 일했어요")

    assert calls[0]["keep_alive"] == -1


@pytest.mark.asyncio
async def test_error_inside_the_stream_raises_unavailable(ollama_calls, monkeypatch):
    # Ollama는 HTTP 200으로 스트림을 시작한 뒤에도 error 필드로 실패를 알린다
    # (예: 모델이 없을 때). raise_for_status로는 잡히지 않는 경로다.
    from app.services.llm import local_ollama as mod

    class _ErrorStream:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):
            yield json.dumps({"error": 'model "qwen2.5:72b" not found'})

    class _Ctx:
        async def __aenter__(self):
            return _ErrorStream()

        async def __aexit__(self, *exc_info):
            return None

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

        def stream(self, *args, **kwargs):
            return _Ctx()

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)

    with pytest.raises(LLMUnavailableError, match="not found"):
        await LocalOllamaProvider().extract_activity_items("아르바이트", "카페에서 일했어요")


@pytest.mark.asyncio
async def test_generate_timeout_is_the_shared_constant(ollama_calls):
    # 호출부 15곳이 각자 숫자를 들고 있으면 한 곳을 빠뜨린 채 서버를 바꾸게 된다.
    import inspect

    from app.services.llm import local_ollama as mod

    source = inspect.getsource(mod)
    assert "timeout=45.0" not in source
    assert mod._GENERATE_TIMEOUT == 240.0


@pytest.mark.asyncio
async def test_extract_activity_period_sends_a_temperature(ollama_calls):
    # temperature 누락으로 이 호출이 매번 TypeError를 냈고, 호출부가 삼켜서
    # 활동기간 AI 추론이 조용히 죽어 있었다. 요청이 실제로 나가는지까지 본다.
    from datetime import date

    calls, canned = ollama_calls
    canned["content"] = json.dumps({"start_date": "2026-03-01", "end_date": "2026-05-31"})
    result = await LocalOllamaProvider().extract_activity_period(
        "카페 아르바이트", [], date(2026, 1, 1), date(2026, 8, 31)
    )

    assert calls[0]["options"]["temperature"] == 0.0
    assert result is not None and result.start_date == date(2026, 3, 1)


def _interview_context(excerpts):
    from datetime import date

    from app.services.llm.base import InterviewContext

    return InterviewContext(
        session_id="s",
        category_label="카페 아르바이트",
        gap_start=date(2025, 1, 1),
        gap_end=date(2025, 12, 31),
        confirmed_facts_so_far=[],
        record_excerpts=excerpts,
    )


def _excerpt():
    from datetime import date

    from app.services.llm.base import RecordExcerpt

    return RecordExcerpt(chunk_id="c-1", text="블로그 원문: 주 3회 오픈 근무", published_at=date(2025, 3, 2))


@pytest.mark.asyncio
async def test_extract_facts_fills_excerpt_text_from_what_we_sent(ollama_calls):
    # 모델에게는 chunk_id만 받는다. 원문을 다시 쓰게 하면 그만큼 decode 시간이
    # 들고, 모델이 바꿔 쓴 text가 인용으로 저장된다.
    calls, canned = ollama_calls
    canned["content"] = json.dumps(
        {"facts": [{"content": "주 3회 근무", "fact_type": "frequency", "based_on": {"type": "record", "chunk_ids": ["c-1"]}}]}
    )

    [fact] = await LocalOllamaProvider().extract_facts(_interview_context([_excerpt()]), "질문", "답", "frequency")

    assert fact.based_on.type == "record"
    assert fact.based_on.excerpts == [_excerpt()]
    assert '"chunk_ids"' in calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_extract_facts_ignores_text_the_model_rewrote_in_the_old_format(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = json.dumps(
        {
            "facts": [
                {
                    "content": "주 3회 근무",
                    "fact_type": "frequency",
                    "based_on": {"type": "record", "excerpts": [{"chunk_id": "c-1", "text": "모델이 지어낸 인용"}]},
                }
            ]
        },
        ensure_ascii=False,
    )

    [fact] = await LocalOllamaProvider().extract_facts(_interview_context([_excerpt()]), "질문", "답", "frequency")

    assert [e.text for e in fact.based_on.excerpts] == ["블로그 원문: 주 3회 오픈 근무"]


@pytest.mark.asyncio
async def test_extract_facts_unknown_chunk_id_is_not_a_citation(ollama_calls):
    _, canned = ollama_calls
    canned["content"] = json.dumps(
        {"facts": [{"content": "주 3회 근무", "fact_type": "frequency", "based_on": {"type": "record", "chunk_ids": ["made-up"]}}]}
    )

    [fact] = await LocalOllamaProvider().extract_facts(_interview_context([_excerpt()]), "질문", "답", "frequency")

    assert fact.based_on.type == "generic_pattern"
    assert fact.based_on.excerpts == []


@pytest.mark.asyncio
async def test_think_is_not_sent_unless_configured(ollama_calls, monkeypatch):
    # 기본은 보내지 않는다 — 운영 Ollama가 이 필드에 어떻게 반응하는지 확인 전이다.
    calls, canned = ollama_calls
    canned["content"] = json.dumps({"items": []})
    monkeypatch.setattr(local_ollama.settings, "local_llm_disable_thinking", False, raising=False)
    await LocalOllamaProvider().extract_activity_items("아르바이트", "카페")

    monkeypatch.setattr(local_ollama.settings, "local_llm_disable_thinking", True, raising=False)
    await LocalOllamaProvider().extract_activity_items("아르바이트", "카페")

    assert "think" not in calls[0]
    assert calls[1]["think"] is False


def test_generation_stats_are_logged_per_call(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(local_ollama.logger, "info", lambda msg, *args: lines.append(msg % args))

    local_ollama._log_generation_stats(
        "extract_facts",
        "qwen2.5:32b",
        12.3,
        {"eval_count": 130, "eval_duration": 10_000_000_000, "prompt_eval_count": 900, "prompt_eval_duration": 1_000_000_000},
    )
    # 계측이 빠진 응답(옛 Ollama, 테스트 스텁)이어도 호출을 실패시키지 않는다.
    local_ollama._log_generation_stats("extract_facts", "qwen2.5:32b", 1.0, {})

    assert "llm extract_facts" in lines[0] and "out=130tok" in lines[0] and "(13.0 tok/s)" in lines[0]
    assert "out=0tok" in lines[1]


@pytest.mark.asyncio
async def test_generate_document_converts_prompt_numbers_to_zero_based_indices(ollama_calls):
    # 프롬프트는 사실을 [1]부터 보여준다. 모델이 "[1]번 사실"이라 답하면 그건
    # facts[0]이어야 한다 — 변환이 없던 동안 인용이 한 칸씩 밀려 저장됐다.
    from app.services.llm.base import ConfirmedFact

    calls, canned = ollama_calls
    canned["content"] = json.dumps(
        {
            "paragraphs": [
                {
                    "topic": "주제",
                    "sentences": [
                        {"text": "첫 문장", "fact_indices": [1]},
                        {"text": "둘째 문장", "fact_indices": [1, 2]},
                        # 0번은 프롬프트에 없는 번호다 — 범위 밖(-1)으로 떨어져 호출부에서 버려진다.
                        {"text": "셋째 문장", "fact_indices": [0, 2, "x"]},
                    ],
                }
            ]
        }
    )
    facts = [
        ConfirmedFact(id="a", content="사실 A", source_type="user_confirmed", fact_type="task"),
        ConfirmedFact(id="b", content="사실 B", source_type="user_confirmed", fact_type="achievement"),
    ]
    draft = await LocalOllamaProvider().generate_document(facts, "neutral", "카페 아르바이트")

    prompt = calls[0]["messages"][1]["content"]
    assert "[1] (user_confirmed) 사실 A" in prompt
    assert [s.fact_indices for s in draft.paragraphs[0].sentences] == [[0], [0, 1], [-1, 1]]
