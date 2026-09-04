from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.models.record import Record
from app.services.record_pipeline import pipeline
from app.services.record_pipeline.parsers import generic, velog

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _fake_response(payload: dict, status_code: int = 200) -> httpx.Response:
    # A request must be attached for Response.raise_for_status() to work.
    request = httpx.Request("POST", "https://v3.velog.io/graphql")
    return httpx.Response(status_code, json=payload, request=request)


# ---------------------------------------------------------------------------
# velog.parse()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_happy_path_returns_title_body_and_date(monkeypatch):
    payload = _load_fixture("velog_read_post.json")

    async def fake_post(self, url, **kwargs):
        assert url == "https://v3.velog.io/graphql"
        variables = kwargs["json"]["variables"]
        assert variables["input"] == {"username": "velopert", "url_slug": "react-portals"}
        return _fake_response(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    text, pub_date = await velog.parse("https://velog.io/@velopert/react-portals")

    assert payload["data"]["post"]["title"] in text
    assert "Portals" in text
    assert pub_date == date(2018, 11, 2)


@pytest.mark.asyncio
async def test_parse_graphql_errors_array_raises_value_error(monkeypatch):
    payload = {"errors": [{"message": "Something went wrong"}]}

    async def fake_post(self, url, **kwargs):
        return _fake_response(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ValueError):
        await velog.parse("https://velog.io/@velopert/react-portals")


@pytest.mark.asyncio
async def test_parse_null_post_raises_value_error(monkeypatch):
    # This is the real shape velog's API returns for a private or deleted
    # post when queried without owner auth: {"data": {"post": null}} with
    # no "errors" entry — verified live against v3.velog.io/graphql.
    payload = {"data": {"post": None}}

    async def fake_post(self, url, **kwargs):
        return _fake_response(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ValueError):
        await velog.parse("https://velog.io/@velopert/some-private-post")


@pytest.mark.asyncio
async def test_parse_empty_body_raises_value_error(monkeypatch):
    payload = {"data": {"post": {"title": "제목", "body": "   ", "released_at": None, "is_private": False}}}

    async def fake_post(self, url, **kwargs):
        return _fake_response(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ValueError):
        await velog.parse("https://velog.io/@velopert/empty-post")


@pytest.mark.asyncio
async def test_parse_bad_url_shape_raises_without_network_call(monkeypatch):
    called = False

    async def fake_post(self, url, **kwargs):
        nonlocal called
        called = True
        return _fake_response({"data": {"post": None}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ValueError):
        await velog.parse("https://velog.io/not-a-valid-post-path")

    assert called is False


# ---------------------------------------------------------------------------
# pipeline._fetch_text() dispatch (regression test for the routing bug)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_dispatches_velog_urls_to_velog_parser_not_generic(monkeypatch):
    calls = {"velog": 0, "generic": 0}

    async def fake_velog_parse(url):
        calls["velog"] += 1
        return "velog text", None

    async def fake_generic_parse(url):
        calls["generic"] += 1
        return "generic text", None

    monkeypatch.setattr(velog, "parse", fake_velog_parse)
    monkeypatch.setattr(generic, "parse", fake_generic_parse)

    record = Record(record_type="blog_url", source_url="https://velog.io/@velopert/react-portals")

    text, _ = await pipeline._fetch_text(record)

    assert calls["velog"] == 1
    assert calls["generic"] == 0
    assert text == "velog text"
    assert record.platform == "velog"
