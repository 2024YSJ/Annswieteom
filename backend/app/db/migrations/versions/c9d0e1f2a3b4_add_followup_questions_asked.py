"""add activity_categories.followup_questions_asked

Splits the per-category question budget in two: questions_asked now tracks
only fixed base questions (never capped — the fixed set for a category type
is short and finite), while this new column tracks AI-added drilldown/
followup questions, capped separately by
interview_orchestrator.MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY. Previously a
single shared cap could force a category to advance before its fixed
"achievement/outcome" question was ever asked, if AI-added questions had
already eaten the whole budget.

Revision ID: c9d0e1f2a3b4
Revises: b3c4d5e6f7a8
Create Date: 2026-09-06 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'activity_categories',
        sa.Column('followup_questions_asked', sa.Integer(), nullable=False, server_default='0'),
    )
    # server_default only needed to backfill existing rows during ADD COLUMN;
    # the ORM always supplies an explicit value going forward (same
    # convention as other non-nullable columns in this codebase).
    op.alter_column('activity_categories', 'followup_questions_asked', server_default=None)


def downgrade() -> None:
    op.drop_column('activity_categories', 'followup_questions_asked')
