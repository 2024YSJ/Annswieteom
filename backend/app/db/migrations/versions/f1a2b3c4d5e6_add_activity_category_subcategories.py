"""add activity_categories.parent_category_id and activity_split_checked

Lets one category be split into sub-categories (e.g. "공모전" -> "OO 공모전",
"XX 공모전") once the interview notices it contains several distinct
activities, so the fixed question set and answered-fact-type tracking apply
per sub-item instead of being shared across all of them.

Revision ID: f1a2b3c4d5e6
Revises: d5f1a9c3e8b7
Create Date: 2026-09-06 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd5f1a9c3e8b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'activity_categories',
        sa.Column('activity_split_checked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('activity_categories', 'activity_split_checked', server_default=None)

    op.add_column('activity_categories', sa.Column('parent_category_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_activity_categories_parent_category_id', 'activity_categories', 'activity_categories',
        ['parent_category_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('fk_activity_categories_parent_category_id', 'activity_categories', type_='foreignkey')
    op.drop_column('activity_categories', 'parent_category_id')
    op.drop_column('activity_categories', 'activity_split_checked')
