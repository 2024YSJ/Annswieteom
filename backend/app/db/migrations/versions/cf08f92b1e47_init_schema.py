"""init schema

Revision ID: cf08f92b1e47
Revises:
Create Date: 2026-08-31 15:23:12.664630

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'cf08f92b1e47'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users (no FK deps)
    op.create_table('users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('nickname', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )

    # activity_categories without session_id FK (added after sessions)
    op.create_table('activity_categories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('category_type', sa.String(length=50), nullable=False),
        sa.Column('custom_label', sa.String(length=200), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("category_type IN ('part_time', 'freelance', 'volunteer', 'study', 'project', 'caregiving', 'travel', 'other')", name='ck_activity_categories_type'),
        sa.CheckConstraint("status IN ('PENDING', 'IN_PROGRESS', 'DONE')", name='ck_activity_categories_status'),
        sa.PrimaryKeyConstraint('id'),
    )

    # sessions → users + activity_categories (cycle resolved via use_alter)
    op.create_table('sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('current_category_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('PERIOD_INPUT', 'CATEGORY_SELECT', 'INTERVIEW_FREQ', 'INTERVIEW_TASK', 'INTERVIEW_ACHIEVEMENT', 'RECORD_UPLOAD', 'GENERATING', 'DONE')", name='ck_sessions_status'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['current_category_id'], ['activity_categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # now add the deferred FK from activity_categories → sessions
    op.create_foreign_key(
        'fk_activity_categories_session_id',
        'activity_categories', 'sessions',
        ['session_id'], ['id'],
        ondelete='CASCADE',
    )

    # refresh_tokens → users
    op.create_table('refresh_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )

    # gap_periods → sessions
    op.create_table('gap_periods',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('end_date >= start_date', name='ck_gap_periods_date_order'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id'),
    )

    # records → sessions
    op.create_table('records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('record_type', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('platform', sa.Text(), nullable=False),
        sa.Column('storage_path', sa.Text(), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('parse_status', sa.Text(), nullable=False),
        sa.Column('parse_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("parse_status IN ('PENDING', 'PROCESSING', 'DONE', 'FAILED')", name='ck_records_parse_status'),
        sa.CheckConstraint("platform IN ('naver', 'tistory', 'velog', 'brunch', 'other', 'unknown')", name='ck_records_platform'),
        sa.CheckConstraint("record_type IN ('blog_url', 'image', 'text')", name='ck_records_type'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # record_chunks → records (Vector 1024)
    op.create_table('record_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('record_id', sa.UUID(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.Date(), nullable=True),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column('embedding_model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['record_id'], ['records.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_record_chunks_embedding ON record_chunks USING ivfflat (embedding vector_cosine_ops)')

    # generated_documents → sessions
    op.create_table('generated_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('tone', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'FINAL')", name='ck_generated_documents_status'),
        sa.CheckConstraint("tone IN ('plain', 'neutral', 'assertive')", name='ck_generated_documents_tone'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # confirmed_facts → activity_categories + record_chunks
    op.create_table('confirmed_facts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('category_id', sa.UUID(), nullable=False),
        sa.Column('fact_type', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('source_record_chunk_id', sa.UUID(), nullable=True),
        sa.Column('ai_draft_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("fact_type IN ('frequency', 'task', 'achievement')", name='ck_confirmed_facts_fact_type'),
        sa.CheckConstraint("source_type IN ('user_confirmed', 'user_edited', 'record_cited')", name='ck_confirmed_facts_source_type'),
        sa.ForeignKeyConstraint(['category_id'], ['activity_categories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_record_chunk_id'], ['record_chunks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # generated_sentences → generated_documents + activity_categories
    op.create_table('generated_sentences',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('category_id', sa.UUID(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('evidence_fact_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('consistency_check_passed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['activity_categories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['generated_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('generated_sentences')
    op.drop_table('confirmed_facts')
    op.drop_table('record_chunks')
    op.drop_table('generated_documents')
    op.drop_table('records')
    op.drop_table('gap_periods')
    op.drop_table('refresh_tokens')
    op.drop_constraint('fk_activity_categories_session_id', 'activity_categories', type_='foreignkey')
    op.drop_table('sessions')
    op.drop_table('activity_categories')
    op.drop_table('users')
