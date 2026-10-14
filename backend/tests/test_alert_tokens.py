"""The alert email tokens.

Unsubscribe (v1) and verification (v1c) links are already in investors'
inboxes, so the exact token strings are pinned here: a change to either
format would stop those links working.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.services.unsubscribe_tokens import (
    create_signed_unsubscribe_token,
    verify_signed_unsubscribe_token,
)
from app.services.verification_tokens import (
    create_signed_verification_token,
    verify_signed_verification_token,
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


def test_the_unsubscribe_token_format_does_not_change() -> None:
    assert create_signed_unsubscribe_token(SUBSCRIPTION_ID, TOKEN_HASH) == UNSUBSCRIBE_TOKEN
    assert verify_signed_unsubscribe_token(UNSUBSCRIBE_TOKEN, TOKEN_HASH) == SUBSCRIPTION_ID


def test_the_verification_token_format_does_not_change() -> None:
    assert (
        create_signed_verification_token(SUBSCRIPTION_ID, TOKEN_HASH, REQUESTED_AT)
        == VERIFICATION_TOKEN
    )
    assert verify_signed_verification_token(
        VERIFICATION_TOKEN,
        TOKEN_HASH,
        REQUESTED_AT,
        now=REQUESTED_AT + timedelta(hours=1),
        ttl=timedelta(hours=24),
    ) == SUBSCRIPTION_ID
