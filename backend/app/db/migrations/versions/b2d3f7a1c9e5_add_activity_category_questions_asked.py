"""add activity_categories.questions_asked

Tracks the total number of questions (fixed + AI-added) asked for a
category, enforcing interview_orchestrator.MAX_QUESTIONS_PER_CATEGORY.

Revision ID: b2d3f7a1c9e5
Revises: a1c2e6f0b7d4
Create Date: 2026-09-05 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2d3f7a1c9e5'
down_revision: Union[str, Sequence[str], None] = 'a1c2e6f0b7d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'activity_categories',
        sa.Column('questions_asked', sa.Integer(), nullable=False, server_default='0'),
    )
    # server_default only needed to backfill existing rows during ADD COLUMN;
    # the ORM always supplies an explicit value going forward (same
    # convention as other non-nullable columns in this codebase).
    op.alter_column('activity_categories', 'questions_asked', server_default=None)


def downgrade() -> None:
    op.drop_column('activity_categories', 'questions_asked')
