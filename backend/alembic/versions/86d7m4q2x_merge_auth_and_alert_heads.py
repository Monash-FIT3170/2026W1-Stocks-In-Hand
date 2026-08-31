"""merge the parallel Cognito repair and alert migration heads

Revision ID: 86d7m4q2xmerge
Revises: 86d2artifactduplicate, 86d4k9m2r
Create Date: 2026-08-30
"""

from typing import Sequence, Union


revision: str = "86d7m4q2xmerge"
down_revision: tuple[str, str] = ("86d2artifactduplicate", "86d4k9m2r")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join both migration histories without changing the database schema."""


def downgrade() -> None:
    """Split the migration histories without changing the database schema."""
