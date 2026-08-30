"""merge the integrated history with the public discussion migration head

Revision ID: 86d7m4q2xpublic
Revises: 86d7m4q2xmerge, 86d5p7k2q
Create Date: 2026-08-30
"""

from typing import Sequence, Union


revision: str = "86d7m4q2xpublic"
down_revision: tuple[str, str] = ("86d7m4q2xmerge", "86d5p7k2q")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join both migration histories without changing the database schema."""


def downgrade() -> None:
    """Split the migration histories without changing the database schema."""
