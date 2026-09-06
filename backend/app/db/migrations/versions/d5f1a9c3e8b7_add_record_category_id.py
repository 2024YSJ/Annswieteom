"""add records.category_id

Lets each uploaded record be tied to the activity category it was requested
for, so the record-request step can walk categories one at a time and
interview context lookup can filter by category directly instead of a loose
label-embedding similarity search.

Revision ID: d5f1a9c3e8b7
Revises: c4e8a2f1d6b3
Create Date: 2026-09-06 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd5f1a9c3e8b7'
down_revision: Union[str, Sequence[str], None] = 'c4e8a2f1d6b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable — existing records (created before categorized uploads existed)
    # have no category to backfill into; application code always supplies one
    # for new rows going forward (see app/api/records.py).
    op.add_column('records', sa.Column('category_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_records_category_id', 'records', 'activity_categories',
        ['category_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('fk_records_category_id', 'records', type_='foreignkey')
    op.drop_column('records', 'category_id')
