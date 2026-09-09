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


def test_records_are_tagged_with_the_category_being_requested(records_client):
    """Records created during the per-category record-request walk should be
    tagged with whichever category is currently being asked for — not left
    uncategorized — and /records/skip should move that current category
    forward one at a time instead of jumping straight to INTERVIEWING."""
    headers = _register_and_login(records_client)
    resp = records_client.post("/api/v1/sessions", headers=headers)
    session_id = resp.json()["id"]
    records_client.post(
        f"/api/v1/sessions/{session_id}/period",
        headers=headers,
        json={"start_date": "2025-01-01", "end_date": "2025-06-30"},
    )
    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/categories",
        headers=headers,
        json={"categories": [{"category_type": "part_time"}, {"category_type": "study"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "RECORD_UPLOAD"

    ctx = records_client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    first_category_id = ctx["current_category"]["id"]
    assert ctx["categories"][0]["category_type"] == "part_time"
    assert first_category_id == ctx["categories"][0]["id"]

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/text",
        headers=headers,
        json={"text": "첫 번째 카테고리 자료"},
    )
    assert resp.status_code == 201
    assert resp.json()["category_id"] == first_category_id

    # One category down, one to go — /records/skip must stay in RECORD_UPLOAD
    # and move current_category_id to the second category, not INTERVIEWING.
    resp = records_client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "RECORD_UPLOAD"
    second_category_id = resp.json()["current_category_id"]
    assert second_category_id != first_category_id

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/text",
        headers=headers,
        json={"text": "두 번째 카테고리 자료"},
    )
    assert resp.status_code == 201
    assert resp.json()["category_id"] == second_category_id

    # Last category done — now it actually reaches INTERVIEWING, reset to the
    # first category for the interview loop.
    resp = records_client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "INTERVIEWING"
    assert resp.json()["current_category_id"] == first_category_id


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


def test_upload_image_is_rejected_since_ocr_was_removed(records_client):
    """Gemini Vision OCR을 제거하면서 이미지 업로드도 같이 없앴다(2026-09-09).
    텍스트를 못 뽑는 이미지는 청크도 임베딩도 만들지 못해 근거가 될 수 없는데,
    받아만 두면 사용자는 근거가 쌓인 줄 안다 — 조용히 저장하느니 거절한다."""
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/upload",
        headers=headers,
        files={"file": ("cert.png", b"fake-png-bytes", "image/png")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "unsupported_file_type"
    # 거절된 업로드는 스토리지에도 아무것도 남기지 않는다.
    assert records_client.fake_storage.uploaded == {}


def test_upload_txt_record_is_a_document_with_original_filename(records_client):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/upload",
        headers=headers,
        files={"file": ("이력서 메모.txt", "텍스트 파일 내용입니다.".encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["record_type"] == "document"
    assert body["original_filename"] == "이력서 메모.txt"
    assert len(records_client.process_document_record_calls) == 1

    resp = records_client.get(f"/api/v1/sessions/{session_id}/records/{body['id']}", headers=headers)
    assert resp.json()["parse_status"] == "DONE"


def test_upload_is_routed_by_extension_not_content_type(records_client):
    """Browsers report unreliable/blank content_type for .md/.hwp, so the
    decision must be made from the filename's extension, not file.content_type."""
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/upload",
        headers=headers,
        files={"file": ("notes.md", b"# heading", "application/octet-stream")},
    )
    assert resp.status_code == 201
    assert resp.json()["record_type"] == "document"


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


def test_records_can_still_be_attached_during_interviewing(records_client):
    """인터뷰 도중 첨부를 다시 허용한다(2026-09-09). 질문을 받기 전에는
    무엇을 올려야 하는지 알 수 없고("아, 이건 블로그에 써둔데"는 질문 뒤에
    나온다), 질문 문구로 청크를 볋터 검색하게 된 이후로는 방금 올린 기록물이
    바로 다음 턴의 근거로 잡힐 수 있다. 첨부 대상 카테고리는 그대로
    session.current_category_id다 — INTERVIEWING에서는 지금 인터뷰 중인 카테고리."""
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(f"/api/v1/sessions/{session_id}/records/skip", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "INTERVIEWING"
    current_category_id = resp.json()["current_category_id"]

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/text",
        headers=headers,
        json={"text": "인터뷰 도중에 추가한 기록물"},
    )
    assert resp.status_code == 201
    assert resp.json()["category_id"] == current_category_id


def test_delete_record_removes_it_and_its_storage_object(records_client):
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.post(
        f"/api/v1/sessions/{session_id}/records/upload",
        headers=headers,
        files={"file": ("증빙.txt", "자격증 사본 메모".encode("utf-8"), "text/plain")},
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


def test_uncited_endpoint_is_not_shadowed_by_the_record_id_route(records_client):
    """`/records/uncited`는 `/records/{record_id}`보다 먼저 선언돼야 한다 —
    아니면 "uncited"가 UUID로 파싱되려다 422로 떨어진다."""
    headers = _register_and_login(records_client)
    session_id = _create_session_at_record_upload(records_client, headers)

    resp = records_client.get(f"/api/v1/sessions/{session_id}/records/uncited", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_uncited_endpoint_rejects_another_users_session(records_client):
    owner_headers = _register_and_login(records_client, email="owner2@example.com")
    session_id = _create_session_at_record_upload(records_client, owner_headers)

    other_headers = _register_and_login(records_client, email="other2@example.com")
    resp = records_client.get(f"/api/v1/sessions/{session_id}/records/uncited", headers=other_headers)
    assert resp.status_code == 403
