"""The alert email tokens.

Unsubscribe (v1) and verification (v1c) links are already in investors'
inboxes, so the exact token strings are pinned here: a change to either
format would stop those links working.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.services.alert_tokens import (
    hash_token,
    is_token_hash,
    new_unsubscribe_secret,
    unsubscribe_token,
    unsubscribe_token_subscription,
    verification_token,
    verification_token_claims,
    verify_unsubscribe_token,
    verify_verification_token,
)

SUBSCRIPTION_ID = UUID("00000000-0000-4000-8000-000000000001")
TOKEN_HASH = "a" * 64
REQUESTED_AT = datetime(2026, 8, 29, 1, 2, 3, 456789, tzinfo=timezone.utc)
UNSUBSCRIBE_TOKEN = (
    "v1.00000000000040008000000000000001.CN0mW1ZXe1-E8Q-odLeBjrc0KKOygGLqrE0PBgmCTQI"
)
VERIFICATION_TOKEN = (
    "v1c.00000000000040008000000000000001.20260829T010203456789Z."
    "ODwwlVh14XEHwaP_Q8Wm-zSynZidF1plip97IFIoRWU"
)
DAY = timedelta(hours=24)


def test_the_unsubscribe_token_format_does_not_change() -> None:
    assert unsubscribe_token(SUBSCRIPTION_ID, TOKEN_HASH) == UNSUBSCRIBE_TOKEN
    assert verify_unsubscribe_token(UNSUBSCRIBE_TOKEN, TOKEN_HASH) == SUBSCRIPTION_ID


def test_the_verification_token_format_does_not_change() -> None:
    assert verification_token(SUBSCRIPTION_ID, TOKEN_HASH, REQUESTED_AT) == VERIFICATION_TOKEN
    assert verify_verification_token(
        VERIFICATION_TOKEN,
        TOKEN_HASH,
        REQUESTED_AT,
        now=REQUESTED_AT + timedelta(hours=1),
        ttl=DAY,
    ) == SUBSCRIPTION_ID


def test_a_new_unsubscribe_secret_is_stored_only_as_its_hash() -> None:
    raw_token, token_hash = new_unsubscribe_secret()

    assert token_hash == hash_token(raw_token)
    assert token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert is_token_hash(token_hash)
    assert raw_token != token_hash
    assert new_unsubscribe_secret()[0] != raw_token
    assert not is_token_hash("A" * 64)
    assert not is_token_hash("a" * 63)


def test_an_unsubscribe_token_names_its_subscription_without_showing_the_hash() -> None:
    subscription_id = uuid4()

    token = unsubscribe_token(subscription_id, TOKEN_HASH)

    assert TOKEN_HASH not in token
    assert unsubscribe_token_subscription(token) == subscription_id
    assert verify_unsubscribe_token(token, TOKEN_HASH) == subscription_id


def test_an_unsubscribe_token_rejects_tampering_and_the_wrong_key() -> None:
    token = unsubscribe_token(uuid4(), "b" * 64)

    assert verify_unsubscribe_token(f"{token}x", "b" * 64) is None
    assert verify_unsubscribe_token(token, "c" * 64) is None
    assert unsubscribe_token_subscription("not-a-token") is None
    assert unsubscribe_token_subscription(VERIFICATION_TOKEN) is None


def test_a_verification_token_names_its_subscription_and_request() -> None:
    subscription_id = uuid4()

    token = verification_token(subscription_id, TOKEN_HASH, REQUESTED_AT)

    assert verification_token_claims(token) == (subscription_id, REQUESTED_AT)
    assert verify_verification_token(
        token,
        TOKEN_HASH,
        REQUESTED_AT,
        now=REQUESTED_AT + timedelta(hours=1),
        ttl=DAY,
    ) == subscription_id


def test_a_verification_token_rejects_tampering_newer_requests_and_expiry() -> None:
    requested_at = datetime.now(timezone.utc)
    token = verification_token(uuid4(), "b" * 64, requested_at)

    assert verify_verification_token(
        f"{token[:-1]}x",
        "b" * 64,
        requested_at,
        now=requested_at,
        ttl=DAY,
    ) is None
    assert verify_verification_token(
        token,
        "b" * 64,
        requested_at + timedelta(minutes=1),
        now=requested_at + timedelta(minutes=1),
        ttl=DAY,
    ) is None
    assert verify_verification_token(
        token,
        "b" * 64,
        requested_at,
        now=requested_at + timedelta(hours=25),
        ttl=DAY,
    ) is None


def test_a_verification_token_rejects_bad_shapes_and_naive_timestamps() -> None:
    assert verification_token_claims("not-a-token") is None
    assert verification_token_claims(UNSUBSCRIBE_TOKEN) is None
    with pytest.raises(ValueError, match="timezone"):
        verification_token(uuid4(), "c" * 64, datetime.now())
    with pytest.raises(ValueError, match="64 lowercase hex"):
        verification_token(uuid4(), "not-a-hash", datetime.now(timezone.utc))
