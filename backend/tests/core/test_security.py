from __future__ import annotations

import uuid

import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_hash_password_verifies_correct_password():
    password_hash = hash_password("correct-horse-battery-staple")

    assert verify_password("correct-horse-battery-staple", password_hash) is True


def test_hash_password_rejects_wrong_password():
    password_hash = hash_password("correct-horse-battery-staple")

    assert verify_password("wrong-password", password_hash) is False


def test_hash_password_never_stores_plaintext():
    password_hash = hash_password("correct-horse-battery-staple")

    assert "correct-horse-battery-staple" not in password_hash


def test_access_token_roundtrip():
    user_id = uuid.uuid4()

    token = create_access_token(user_id)

    assert decode_access_token(token) == user_id


def test_access_token_rejects_garbage():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.valid.jwt")


def test_access_token_rejects_tampered_signature():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    header, payload, signature = token.split(".")
    # Flip the *first* base64url char of the signature rather than the last:
    # the last char of a base64url-encoded 32-byte hash only carries a couple
    # of bits (32 bytes doesn't divide evenly into 6-bit groups), so flipping
    # it can sometimes decode to the same bytes and make this test flaky.
    tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = f"{header}.{payload}.{tampered_signature}"

    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_refresh_token_is_not_stored_in_plaintext_form():
    raw_token = generate_refresh_token()

    assert hash_refresh_token(raw_token) != raw_token


def test_refresh_token_hash_is_deterministic():
    raw_token = generate_refresh_token()

    assert hash_refresh_token(raw_token) == hash_refresh_token(raw_token)


def test_generate_refresh_token_is_unique_per_call():
    assert generate_refresh_token() != generate_refresh_token()
