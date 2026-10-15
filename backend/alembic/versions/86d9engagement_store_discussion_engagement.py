"""store public discussion engagement

Revision ID: 86d9engagement
Revises: 86d9statuschecks
Create Date: 2026-10-07

The public discussion collector now stores each post's engagement in
``artifact_metadata["engagement"]``, so posts for a ticker rank the same way
whatever their source. This fills it in for posts stored before, using each
source's rule at this revision: Reddit's score, Bluesky's likes, Mastodon's
favourites plus reblogs plus replies, and 0 for blogs. Metadata that is SQL
NULL or not a JSON object, such as the JSON null SQLAlchemy stores for None,
counts as empty.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "86d9engagement"
down_revision: Union[str, None] = "86d9statuschecks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _count(key: str) -> str:
    value = f"artifact_metadata->>'{key}'"
    return f"(CASE WHEN {value} ~ '^-?[0-9]+$' THEN ({value})::bigint ELSE 0 END)"


BACKFILL = f"""
UPDATE artifacts
SET artifact_metadata = jsonb_set(
    CASE
        WHEN jsonb_typeof(artifact_metadata) = 'object' THEN artifact_metadata
        ELSE '{{}}'::jsonb
    END,
    '{{engagement}}',
    to_jsonb(
        CASE source_type
            WHEN 'reddit' THEN {_count('score')}
            WHEN 'bluesky' THEN {_count('like_count')}
            WHEN 'mastodon' THEN {_count('favourites_count')}
                + {_count('reblogs_count')}
                + {_count('replies_count')}
            ELSE 0
        END
    )
)
WHERE source_type IN ('reddit', 'bluesky', 'mastodon', 'blog')
  AND (
    jsonb_typeof(artifact_metadata) IS DISTINCT FROM 'object'
    OR NOT artifact_metadata ? 'engagement'
  )
"""  # nosec B608 - built only from the fixed key names above, never from input


def upgrade() -> None:
    op.execute(BACKFILL)


def downgrade() -> None:
    op.execute(
        "UPDATE artifacts SET artifact_metadata = artifact_metadata - 'engagement' "
        "WHERE source_type IN ('reddit', 'bluesky', 'mastodon', 'blog') "
        "AND artifact_metadata ? 'engagement'"
    )
