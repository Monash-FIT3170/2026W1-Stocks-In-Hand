"""The tokens alert emails carry: unsubscribe tokens and verification tokens.

A subscription's unsubscribe secret is a random raw token. The database keeps
only its SHA-256 hash, which also signs both kinds of token with HMAC-SHA256,
so a token never shows the hash it was signed with.

An unsubscribe token, ``v1.<subscription>.<signature>``, never expires. A
verification token, ``v1c.<subscription>.<request time>.<signature>``, names
the verification request it confirms. Links in emails already sent carry both
formats, so neither format may change.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID


TOKEN_HASH: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
_UNSUBSCRIBE_FORMAT = "v1"
_VERIFICATION_FORMAT = "v1c"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"
# A request time this far ahead of the clock is still accepted, for clock skew.
_FUTURE_LEEWAY = timedelta(minutes=5)


def is_token_hash(value: str) -> bool:
    """Whether ``value`` has the stored form of an unsubscribe secret."""
    return TOKEN_HASH.fullmatch(value) is not None


def new_unsubscribe_secret() -> tuple[str, str]:
    """A new raw unsubscribe token, and the hash stored in its place."""
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_token(raw_token)


def hash_token(raw_token: str) -> str:
    """The stored form of a raw unsubscribe token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def unsubscribe_token(subscription_id: UUID, token_hash: str) -> str:
    """The signed unsubscribe token for one subscription."""
    return _signed(token_hash, f"{_UNSUBSCRIBE_FORMAT}.{subscription_id.hex}")


def unsubscribe_token_subscription(token: str) -> UUID | None:
    """The subscription a well-shaped unsubscribe token names, not yet verified."""
    parts = str(token).split(".")
    if len(parts) != 3 or parts[0] != _UNSUBSCRIBE_FORMAT:
        return None
    return _subscription_id(parts[1])


def verify_unsubscribe_token(token: str, token_hash: str) -> UUID | None:
    """The subscription an unsubscribe token signed with ``token_hash`` names, or None."""
    subscription_id = unsubscribe_token_subscription(token)
    if subscription_id is None:
        return None
    if not _matches(token, unsubscribe_token(subscription_id, token_hash)):
        return None
    return subscription_id


def verification_token(
    subscription_id: UUID,
    token_hash: str,
    requested_at: datetime,
) -> str:
    """The signed verification token for the request made at ``requested_at``."""
    payload = f"{_VERIFICATION_FORMAT}.{subscription_id.hex}.{_timestamp(requested_at)}"
    return _signed(token_hash, payload)


def verification_token_claims(token: str) -> tuple[UUID, datetime] | None:
    """The subscription and request a well-shaped verification token names, not yet verified."""
    parts = str(token).split(".")
    if len(parts) != 4 or parts[0] != _VERIFICATION_FORMAT:
        return None
    subscription_id = _subscription_id(parts[1])
    if subscription_id is None:
        return None
    try:
        requested_at = datetime.strptime(parts[2], _TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    return subscription_id, requested_at


def verify_verification_token(
    token: str,
    token_hash: str,
    expected_requested_at: datetime,
    *,
    now: datetime,
    ttl: timedelta,
) -> UUID | None:
    """The subscription a verification token names, or None.

    The token must be signed with ``token_hash``, name the request made at
    ``expected_requested_at``, and be younger than ``ttl``.
    """
    claims = verification_token_claims(token)
    if claims is None:
        return None
    subscription_id, requested_at = claims
    expected_requested_at = _aware_utc(expected_requested_at, field="expected_requested_at")
    now = _aware_utc(now, field="now")
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    if requested_at != expected_requested_at:
        return None
    if requested_at > now + _FUTURE_LEEWAY or now - requested_at > ttl:
        return None
    expected = verification_token(subscription_id, token_hash, requested_at)
    if not _matches(token, expected):
        return None
    return subscription_id


def _signed(token_hash: str, payload: str) -> str:
    """``payload`` and its signature, in unpadded base64url, joined by a dot."""
    signature = hmac.new(
        _signing_key(token_hash),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def _matches(token: str, expected: str) -> bool:
    """Whether ``token`` is the ``expected`` signed token, compared in constant time.

    Compares bytes, because ``hmac.compare_digest`` raises ``TypeError`` for
    text with a non-ASCII character, and a token from a request may have one.
    """
    return hmac.compare_digest(str(token).encode("utf-8"), expected.encode("ascii"))


def _signing_key(token_hash: str) -> bytes:
    """The stored hash, a random secret for each subscription, as an HMAC key."""
    if not is_token_hash(token_hash):
        raise ValueError("unsubscribe token hash must be 64 lowercase hex characters")
    return bytes.fromhex(token_hash)


def _subscription_id(value: str) -> UUID | None:
    """The subscription id ``value`` spells in its canonical hex form, or None."""
    try:
        subscription_id = UUID(hex=value)
    except ValueError:
        return None
    if subscription_id.hex != value:
        return None
    return subscription_id


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _aware_utc(value, field="requested_at").strftime(_TIMESTAMP_FORMAT)
