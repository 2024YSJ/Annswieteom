"""users: add is_guest, relax email/password_hash to nullable

Phase 1 of the Claude-Desktop-style UI redesign: guest sessions are just
User rows with is_guest=True and no email/password_hash. Postgres and
SQLite both allow multiple NULLs under a UNIQUE constraint, so relaxing
email to nullable doesn't require any uniqueness workaround.

Revision ID: e28bf881dfa3
Revises: 416fb65dbf6f
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e28bf881dfa3'
down_revision: Union[str, Sequence[str], None] = '416fb65dbf6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('is_guest', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('users', 'email', existing_type=sa.String(length=255), nullable=True)
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=False)
    op.alter_column('users', 'email', existing_type=sa.String(length=255), nullable=False)
    op.drop_column('users', 'is_guest')
