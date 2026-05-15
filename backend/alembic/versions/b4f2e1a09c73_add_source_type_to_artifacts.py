"""add source_type to artifacts

Revision ID: b4f2e1a09c73
Revises: 93468da15455
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4f2e1a09c73'
down_revision: Union[str, None] = '93468da15455'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('artifacts', sa.Column('source_type', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('artifacts', 'source_type')
