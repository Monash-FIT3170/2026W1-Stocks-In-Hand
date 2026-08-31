"""Generalise the alert provider delivery metadata.

Revision ID: 86d4k9m2r
Revises: 86d4k9m2q
Create Date: 2026-08-29
"""

# Alembic requires lower-case revision metadata and exposes ``op`` at runtime.
# pylint: disable=invalid-name,no-name-in-module

from typing import Sequence, Union

from alembic import op


revision: str = "86d4k9m2r"
down_revision: Union[str, None] = "86d4k9m2q"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename the SES-specific message identifier without losing history."""
    op.alter_column(
        "alert_deliveries",
        "ses_message_id",
        new_column_name="provider_message_id",
    )


def downgrade() -> None:
    """Restore the original SES-specific column name."""
    op.alter_column(
        "alert_deliveries",
        "provider_message_id",
        new_column_name="ses_message_id",
    )
