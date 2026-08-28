"""add Cognito identity link to investors

Revision ID: 86d2cognitoidentity
Revises: 86d2supabasesecurity
Create Date: 2026-08-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d2cognitoidentity"
down_revision: Union[str, None] = "86d2supabasesecurity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investors",
        sa.Column("cognito_sub", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_investors_cognito_sub",
        "investors",
        ["cognito_sub"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_investors_cognito_sub", table_name="investors")
    op.drop_column("investors", "cognito_sub")
