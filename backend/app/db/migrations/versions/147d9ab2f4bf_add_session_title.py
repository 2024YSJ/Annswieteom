"""sessions: add title column

Lets a user rename a session in the sidebar instead of only seeing its
creation date. Nullable with no default — a session without a title falls
back to displaying its creation date (frontend sessions/layout.tsx).

Revision ID: 147d9ab2f4bf
Revises: e28bf881dfa3
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '147d9ab2f4bf'
down_revision: Union[str, Sequence[str], None] = 'e28bf881dfa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('title', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('sessions', 'title')
