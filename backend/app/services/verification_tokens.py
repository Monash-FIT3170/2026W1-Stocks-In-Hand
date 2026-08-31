"""Signed, expiring email-verification tokens for alert subscriptions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID


_FORMAT_VERSION = "v1c"
_TOKEN_HASH = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"
_FUTURE_LEEWAY = timedelta(minutes=5)


def _signing_key(unsubscribe_token_hash: str) -> bytes:
    if not _TOKEN_HASH.fullmatch(unsubscribe_token_hash):
        raise ValueError(
            "unsubscribe token hash must be 64 lowercase hex characters"
        )
    return bytes.fromhex(unsubscribe_token_hash)


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _aware_utc(value, field="requested_at").strftime(_TIMESTAMP_FORMAT)


def _payload(subscription_id: UUID, requested_at: datetime) -> str:
    return f"{_FORMAT_VERSION}.{subscription_id.hex}.{_timestamp(requested_at)}"


def create_signed_verification_token(
    subscription_id: UUID,
    unsubscribe_token_hash: str,
    requested_at: datetime,
) -> str:
    """Create a token bound to one subscription verification request."""
    payload = _payload(subscription_id, requested_at)
    signature = hmac.new(
        _signing_key(unsubscribe_token_hash),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode(
        "ascii"
    )
    return f"{payload}.{encoded_signature}"


def verification_token_claims(token: str) -> tuple[UUID, datetime] | None:
    """Return untrusted lookup claims from a well-shaped token."""
    parts = str(token).split(".")
    if len(parts) != 4 or parts[0] != _FORMAT_VERSION:
        return None
    try:
        subscription_id = UUID(hex=parts[1])
        requested_at = datetime.strptime(parts[2], _TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except (AttributeError, ValueError):
        return None
    if subscription_id.hex != parts[1]:
        return None
    return subscription_id, requested_at


def verify_signed_verification_token(
    token: str,
    unsubscribe_token_hash: str,
    expected_requested_at: datetime,
    *,
    now: datetime,
    ttl: timedelta,
) -> UUID | None:
    """Verify the signature, request generation, and lifetime of a token."""
    claims = verification_token_claims(token)
    if claims is None:
        return None
    subscription_id, requested_at = claims
    expected_requested_at = _aware_utc(
        expected_requested_at,
        field="expected_requested_at",
    )
    now = _aware_utc(now, field="now")
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    if requested_at != expected_requested_at:
        return None
    if requested_at > now + _FUTURE_LEEWAY or now - requested_at > ttl:
        return None
    expected = create_signed_verification_token(
        subscription_id,
        unsubscribe_token_hash,
        requested_at,
    )
    if not hmac.compare_digest(str(token), expected):
        return None
    return subscription_id
