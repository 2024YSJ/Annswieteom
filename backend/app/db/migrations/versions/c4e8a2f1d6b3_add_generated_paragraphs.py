"""add generated_paragraphs table and generated_sentences.paragraph_id

Lets document generation group similar-themed sentences into paragraphs
(topic label + a user_confirmed flag) instead of one flat sentence list.

Revision ID: c4e8a2f1d6b3
Revises: b2d3f7a1c9e5
Create Date: 2026-09-05 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c4e8a2f1d6b3'
down_revision: Union[str, Sequence[str], None] = 'b2d3f7a1c9e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generated_paragraphs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('topic', sa.Text(), nullable=False),
        sa.Column('user_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['document_id'], ['generated_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.alter_column('generated_paragraphs', 'user_confirmed', server_default=None)

    # nullable — existing sentences (created before this column existed) have
    # no group to backfill into; they're treated as their own single-sentence
    # paragraph at read time instead (see app/api/document.py::_document_read).
    op.add_column('generated_sentences', sa.Column('paragraph_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_generated_sentences_paragraph_id', 'generated_sentences', 'generated_paragraphs',
        ['paragraph_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('fk_generated_sentences_paragraph_id', 'generated_sentences', type_='foreignkey')
    op.drop_column('generated_sentences', 'paragraph_id')
    op.drop_table('generated_paragraphs')
