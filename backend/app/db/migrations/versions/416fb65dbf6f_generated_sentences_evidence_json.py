"""generated_sentences.evidence_fact_ids: JSONB -> generic JSON

Discovered while implementing B-4 (document generation): the SQLite test
fixtures can't compile JSONB (same class of issue as sessions.pending_draft,
fixed in 90edf5d28f6a), and this column is never queried by its JSON
content — just written and read back whole — so JSONB's indexing benefits
don't apply here either.

Revision ID: 416fb65dbf6f
Revises: 90edf5d28f6a
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '416fb65dbf6f'
down_revision: Union[str, Sequence[str], None] = '90edf5d28f6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'generated_sentences',
        'evidence_fact_ids',
        type_=sa.JSON(),
        postgresql_using='evidence_fact_ids::json',
    )


def downgrade() -> None:
    op.alter_column(
        'generated_sentences',
        'evidence_fact_ids',
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using='evidence_fact_ids::jsonb',
    )
