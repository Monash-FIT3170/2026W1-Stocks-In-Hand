"""Contracts for signed alert unsubscribe tokens."""

# pylint: disable=duplicate-code

import uuid

from app.services.unsubscribe_tokens import (
    create_signed_unsubscribe_token,
    subscription_id_from_signed_token,
    verify_signed_unsubscribe_token,
)


def test_signed_unsubscribe_token_round_trip_hides_the_stored_hash() -> None:
    """The email bearer token must not disclose its database signing key."""
    subscription_id = uuid.uuid4()
    token_hash = "a" * 64

    token = create_signed_unsubscribe_token(subscription_id, token_hash)

    assert token_hash not in token
    assert subscription_id_from_signed_token(token) == subscription_id
    assert verify_signed_unsubscribe_token(token, token_hash) == subscription_id


def test_signed_unsubscribe_token_rejects_tampering_and_the_wrong_key() -> None:
    """A changed payload or signature cannot authorize an unsubscribe."""
    subscription_id = uuid.uuid4()
    token_hash = "b" * 64
    token = create_signed_unsubscribe_token(subscription_id, token_hash)

    assert verify_signed_unsubscribe_token(f"{token}x", token_hash) is None
    assert verify_signed_unsubscribe_token(token, "c" * 64) is None
    assert subscription_id_from_signed_token("not-a-token") is None
