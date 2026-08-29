"""Security contracts for signed alert-email verification tokens."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.verification_tokens import (
    create_signed_verification_token,
    verification_token_claims,
    verify_signed_verification_token,
)


def test_signed_verification_token_round_trip() -> None:
    """A current token must retain and verify its subscription identity."""
    subscription_id = uuid4()
    requested_at = datetime(2026, 8, 29, 1, 2, 3, 456789, tzinfo=timezone.utc)
    token = create_signed_verification_token(
        subscription_id,
        "a" * 64,
        requested_at,
    )

    assert verification_token_claims(token) == (subscription_id, requested_at)
    assert verify_signed_verification_token(
        token,
        "a" * 64,
        requested_at,
        now=requested_at + timedelta(hours=1),
        ttl=timedelta(hours=24),
    ) == subscription_id


def test_token_rejects_tampering_newer_requests_and_expiry() -> None:
    """Signatures, request generations, and expiry must all be enforced."""
    subscription_id = uuid4()
    requested_at = datetime.now(timezone.utc)
    token = create_signed_verification_token(
        subscription_id,
        "b" * 64,
        requested_at,
    )

    assert verify_signed_verification_token(
        f"{token[:-1]}x",
        "b" * 64,
        requested_at,
        now=requested_at,
        ttl=timedelta(hours=24),
    ) is None
    assert verify_signed_verification_token(
        token,
        "b" * 64,
        requested_at + timedelta(minutes=1),
        now=requested_at + timedelta(minutes=1),
        ttl=timedelta(hours=24),
    ) is None
    assert verify_signed_verification_token(
        token,
        "b" * 64,
        requested_at,
        now=requested_at + timedelta(hours=25),
        ttl=timedelta(hours=24),
    ) is None


def test_token_rejects_bad_shapes_and_naive_timestamps() -> None:
    """Malformed tokens and ambiguous timestamps must fail closed."""
    assert verification_token_claims("not-a-token") is None
    with pytest.raises(ValueError, match="timezone"):
        create_signed_verification_token(uuid4(), "c" * 64, datetime.now())
    with pytest.raises(ValueError, match="64 lowercase hex"):
        create_signed_verification_token(
            uuid4(),
            "not-a-hash",
            datetime.now(timezone.utc),
        )
