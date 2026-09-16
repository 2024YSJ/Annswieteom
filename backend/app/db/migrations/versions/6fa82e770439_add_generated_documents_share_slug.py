"""add generated_documents.share_slug

Lets a FINAL document be shared publicly via a short opaque slug instead of
its session_id — session_id is guessable-adjacent (sequential-feeling UUIDs
aren't, but exposing it at all would still let a client probe
/api/v1/sessions/{id}/... endpoints). The public share route
(app/api/share.py) only ever looks documents up by this slug.

Revision ID: 6fa82e770439
Revises: d2a6f19e4b73
Create Date: 2026-09-16 13:58:43.174582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6fa82e770439'
down_revision: Union[str, Sequence[str], None] = 'd2a6f19e4b73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable — most documents are never shared, and there is nothing to
    # backfill for existing rows (a slug is only minted on demand by
    # POST /sessions/{id}/document/share).
    op.add_column('generated_documents', sa.Column('share_slug', sa.String(length=16), nullable=True))
    op.create_unique_constraint('uq_generated_documents_share_slug', 'generated_documents', ['share_slug'])


def downgrade() -> None:
    op.drop_constraint('uq_generated_documents_share_slug', 'generated_documents', type_='unique')
    op.drop_column('generated_documents', 'share_slug')
