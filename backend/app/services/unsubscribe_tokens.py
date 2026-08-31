"""Signed unsubscribe tokens that never expose the stored token hash."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from uuid import UUID


_FORMAT_VERSION = "v1"
_TOKEN_HASH = re.compile(r"[0-9a-f]{64}")


def _signing_key(unsubscribe_token_hash: str) -> bytes:
    """Use the random stored hash as a per-subscription HMAC secret."""
    if not _TOKEN_HASH.fullmatch(unsubscribe_token_hash):
        raise ValueError(
            "unsubscribe token hash must be 64 lowercase hex characters"
        )
    return bytes.fromhex(unsubscribe_token_hash)


def _payload(subscription_id: UUID) -> str:
    return f"{_FORMAT_VERSION}.{subscription_id.hex}"


def create_signed_unsubscribe_token(
    subscription_id: UUID,
    unsubscribe_token_hash: str,
) -> str:
    """Create a stable bearer token without revealing its signing key."""
    payload = _payload(subscription_id)
    signature = hmac.new(
        _signing_key(unsubscribe_token_hash),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode(
        "ascii"
    )
    return f"{payload}.{encoded_signature}"


def subscription_id_from_signed_token(token: str) -> UUID | None:
    """Return the untrusted lookup ID embedded in a well-shaped token."""
    parts = str(token).split(".")
    if len(parts) != 3 or parts[0] != _FORMAT_VERSION:
        return None
    try:
        subscription_id = UUID(hex=parts[1])
    except (AttributeError, ValueError):
        return None
    if subscription_id.hex != parts[1]:
        return None
    return subscription_id


def verify_signed_unsubscribe_token(
    token: str,
    unsubscribe_token_hash: str,
) -> UUID | None:
    """Verify a token in constant time and return its subscription ID."""
    subscription_id = subscription_id_from_signed_token(token)
    if subscription_id is None:
        return None
    expected = create_signed_unsubscribe_token(
        subscription_id,
        unsubscribe_token_hash,
    )
    if not hmac.compare_digest(str(token), expected):
        return None
    return subscription_id
