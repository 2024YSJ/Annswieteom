"""add job search keyword and completed fields

Revision ID: a194faedf943
Revises: 4d7aacb4bfe8
Create Date: 2026-09-08 10:29:47.572349

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a194faedf943'
down_revision: Union[str, Sequence[str], None] = '4d7aacb4bfe8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Hand-edited from the autogenerate output: dropped two unrelated changes
    (generated_paragraphs.created_at NOT NULL, record_chunks ivfflat index
    drop) that autogenerate picked up as pre-existing drift against the dev
    DB — same known issue noted in earlier migrations, nothing to do with
    this change. Added server_default for the new NOT NULL
    completed_fields column since job_search_preferences may already have
    rows (existing confirmed preferences).
    """
    op.add_column('job_search_preferences', sa.Column('desired_keyword', sa.String(length=200), nullable=True))
    op.add_column(
        'job_search_preferences',
        sa.Column('completed_fields', sa.JSON(), nullable=False, server_default='[]'),
    )
    op.alter_column('job_search_preferences', 'completed_fields', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_search_preferences', 'completed_fields')
    op.drop_column('job_search_preferences', 'desired_keyword')
