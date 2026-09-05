from __future__ import annotations

from datetime import date

from app.services.record_pipeline.parsers import velog


def _register_and_login(client, email="alice@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "nickname": "Alice"},
    )
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_session_at_record_upload(client, headers):
    resp = client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    assert resp.status_code == 200

    resp = client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": "part_time"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "RECORD_UPLOAD"

    return session_id


def test_create_blog_record_returns_pending_then_polling_shows_done(records_client):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records",
        headers=headers,
        json={"record_type": "blog_url", "source_url": "https://blog.naver.com/someone/1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 1
    assert body[0]["record_type"] == "blog_url"

    record_id = body[0]["id"]
    assert len(records_client.process_record_calls) == 1

    resp = records_client.get(f"/api/v1/sessions/{session_id}/records/{record_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["parse_status"] == "DONE"


def test_create_blog_record_from_velog_listing_page_imports_every_post_in_range(records_client, monkeypatch):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)  # gap period: 2025-01-01..2025-06-30

    async def fake_list_posts_in_range(username, gap_start, gap_end):
        assert username == "sjyoon1101"
        assert (gap_start, gap_end) == (date(2025, 1, 1), date(2025, 6, 30))
        return [
            velog.ListedPost(url_slug="post-a", title="A", released_at=date(2025, 3, 1)),
            velog.ListedPost(url_slug="post-b", title="B", released_at=date(2025, 4, 1)),
        ]

    monkeypatch.setattr(velog, "list_posts_in_range", fake_list_posts_in_range)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records",
        headers=headers,
        json={"record_type": "blog_url", "source_url": "https://velog.io/@sjyoon1101/posts"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 2
    assert {r["source_url"] for r in body} == {
        "https://velog.io/@sjyoon1101/post-a",
        "https://velog.io/@sjyoon1101/post-b",
    }
    assert len(records_client.process_record_calls) == 2


def test_create_blog_record_from_velog_listing_page_with_no_posts_in_range_returns_422(records_client, monkeypatch):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    async def fake_list_posts_in_range(username, gap_start, gap_end):
        return []

    monkeypatch.setattr(velog, "list_posts_in_range", fake_list_posts_in_range)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records",
        headers=headers,
        json={"record_type": "blog_url", "source_url": "https://velog.io/@sjyoon1101/posts"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "no_posts_in_period"
    assert len(records_client.process_record_calls) == 0


def test_create_text_record(records_client):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/text",
        headers=headers,
        json={"text": "이 기간 동안 스터디를 진행했습니다."},
    )
    assert resp.status_code == 201
    assert resp.json()["record_type"] == "text"
    assert len(records_client.process_record_calls) == 1


def test_upload_image_record_stores_bytes_under_isolated_path(records_client):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/upload",
        headers=headers,
        files={"file": ("cert.png", b"fake-png-bytes", "image/png")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["record_type"] == "image"
    assert len(records_client.process_image_record_calls) == 1

    # The uploaded bytes ended up under exactly one path, scoped by user/session/record.
    stored_paths = list(records_client.fake_storage.uploaded.keys())
    assert len(stored_paths) == 1
    assert stored_paths[0].startswith(f"records/")
    assert session_id in stored_paths[0]
    assert records_client.fake_storage.uploaded[stored_paths[0]] == b"fake-png-bytes"

    resp = records_client.get(f"/api/v1/sessions/{session_id}/records/{body['id']}", headers=headers)
    assert resp.json()["parse_status"] == "DONE"


def test_upload_rejects_unsupported_content_type(records_client):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/upload",
        headers=headers,
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code == 400


def test_records_endpoints_require_record_upload_status(records_client):
    headers = _register_and_login(records_client)
    resp = records_client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]  # still PERIOD_INPUT

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records",
        headers=headers,
        json={"record_type": "blog_url", "source_url": "https://blog.naver.com/someone/1"},
    )
    assert resp.status_code == 409


def test_records_can_still_be_attached_once_interviewing(records_client):
    """Records used to be gated to RECORD_UPLOAD only; the interview can now
    be attached to at any point through the interview phase too, so a session
    that has already moved past records/skip into INTERVIEWING must still
    accept new records (evidence for a category the user hasn't finished yet)."""
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "INTERVIEWING"

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/text",
        headers=headers,
        json={"text": "인터뷰 도중에 추가한 기록물"},
    )
    assert resp.status_code == 201


def test_delete_record_removes_it_and_its_storage_object(records_client):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/upload",
        headers=headers,
        files={"file": ("cert.png", b"fake-png-bytes", "image/png")},
    )
    record_id = resp.json()["id"]
    stored_path = next(iter(records_client.fake_storage.uploaded.keys()))

    resp = records_client.delete(f"/api/v1/sessions/{session_id}/records/{record_id}", headers=headers)
    assert resp.status_code == 204
    assert stored_path in records_client.fake_storage.deleted
    assert stored_path not in records_client.fake_storage.uploaded

    resp = records_client.get(f"/api/v1/sessions/{session_id}/records/{record_id}", headers=headers)
    assert resp.status_code == 404


def test_other_users_session_returns_403_and_wrong_session_record_returns_404(records_client):
    headers_a = _register_and_login(records_client, email="a@example.com")
    session_id = _create_session_at_record_upload(records_client, headers_a)
    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/text",
        headers=headers_a,
        json={"text": "a's note"},
    )
    record_id = resp.json()["id"]

    headers_b = _register_and_login(records_client, email="b@example.com")

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/text",
        headers=headers_b,
        json={"text": "b trying to write into a's session"},
    )
    assert resp.status_code == 403

    resp = records_client.get(f"/api/v1/sessions/{session_id}/records/{record_id}", headers=headers_b)
    assert resp.status_code == 403

    # b's own session, but referencing a's record id -> 404, not leaking a's data
    session_b_id = _create_session_at_record_upload(records_client, headers_b)
    resp = records_client.get(f"/api/v1/sessions/{session_b_id}/records/{record_id}", headers=headers_b)
    assert resp.status_code == 404
