"""store each analysed announcement under its category's artifact type

Revision ID: 86d9artifacttypes
Revises: 86d9engagement
Create Date: 2026-10-14

Analysis stored every pipeline announcement as ``asx_announcement_other``,
whatever its category, while the local loader stored the category's own
type. Analysis now stores the category's type too. This gives it to the
announcements stored before, for the three categories that have their own
type: their ``artifact_metadata["category"]`` names the category.

The pairs are a snapshot of the category taxonomy at this revision; a
category that gains its own type later needs its own data migration.
Readers use the metadata category before the type, so no label or
sentiment bucket changes. News and public discussion keep their types.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d9artifacttypes"
down_revision: Union[str, None] = "86d9engagement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ARTIFACT_TYPES = (
    ("DividendAnnouncement", "dividend_announcement"),
    ("SecurityNotification", "security_notification"),
    ("LeadershipChange", "leadership_change"),
)

STORE_ARTIFACT_TYPE = sa.text(
    """
    UPDATE artifacts
    SET artifact_type = :artifact_type
    WHERE source_type = 'asx_announcement'
      AND artifact_metadata ->> 'category' = :category
      AND artifact_type <> :artifact_type
    """
)


def store_announcement_artifact_types(bind) -> None:
    for category, artifact_type in ARTIFACT_TYPES:
        bind.execute(
            STORE_ARTIFACT_TYPE,
            {"category": category, "artifact_type": artifact_type},
        )


def upgrade() -> None:
    store_announcement_artifact_types(op.get_bind())


def downgrade() -> None:
    # Keep the types: the code before this revision reads the metadata
    # category first, and the local loader already stored these types.
    pass
