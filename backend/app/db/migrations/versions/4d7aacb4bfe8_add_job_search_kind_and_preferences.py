"""add job search kind and preferences

Revision ID: 4d7aacb4bfe8
Revises: c9d0e1f2a3b4
Create Date: 2026-09-07 15:26:19.608049

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4d7aacb4bfe8'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_SESSION_STATUSES = (
    "PERIOD_INPUT", "CATEGORY_SELECT", "RECORD_UPLOAD",
    "INTERVIEWING", "RESULT_GENERATE", "RESULT_REVIEW",
)
_NEW_SESSION_STATUSES = _OLD_SESSION_STATUSES + (
    "JOB_PREFERENCES_INPUT", "JOB_SEARCHING", "JOB_RESULTS_REVIEW",
)


def upgrade() -> None:
    """Upgrade schema.

    Hand-edited from the autogenerate output: dropped two unrelated changes
    autogenerate picked up as drift against the live dev DB (a
    generated_paragraphs.created_at NOT NULL tweak and a record_chunks
    ivfflat index it can't fully introspect for pgvector) that have nothing
    to do with this feature — see 02_database_schema.md checklist's existing
    note that autogenerate needs manual review, especially for anything it
    can't diff cleanly. Also manually added: a server_default for the new
    NOT NULL `sessions.kind` column (autogenerate never adds one, but this
    table already has rows) and the ck_sessions_status constraint update
    (autogenerate does not detect a body change to an existing named CHECK
    constraint, only add/remove).
    """
    op.create_table('job_search_preferences',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('desired_salary_min', sa.Integer(), nullable=True),
    sa.Column('desired_salary_max', sa.Integer(), nullable=True),
    sa.Column('desired_location', sa.String(length=200), nullable=True),
    sa.Column('education_level', sa.String(length=100), nullable=True),
    sa.Column('career_years', sa.Integer(), nullable=True),
    sa.Column('work_style_tags', sa.JSON(), nullable=False),
    sa.Column('free_text_notes', sa.Text(), nullable=True),
    sa.Column('last_searched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_results', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id')
    )
    op.add_column('sessions', sa.Column('kind', sa.String(length=20), nullable=False, server_default='gap_fill'))
    op.add_column('sessions', sa.Column('linked_gap_session_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_sessions_linked_gap_session_id', 'sessions', 'sessions',
        ['linked_gap_session_id'], ['id'], ondelete='SET NULL',
    )
    op.create_check_constraint('ck_sessions_kind', 'sessions', "kind IN ('gap_fill', 'job_search')")

    op.drop_constraint('ck_sessions_status', 'sessions', type_='check')
    op.create_check_constraint('ck_sessions_status', 'sessions', f"status IN {_NEW_SESSION_STATUSES}")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_sessions_status', 'sessions', type_='check')
    op.create_check_constraint('ck_sessions_status', 'sessions', f"status IN {_OLD_SESSION_STATUSES}")

    op.drop_constraint('ck_sessions_kind', 'sessions', type_='check')
    op.drop_constraint('fk_sessions_linked_gap_session_id', 'sessions', type_='foreignkey')
    op.drop_column('sessions', 'linked_gap_session_id')
    op.drop_column('sessions', 'kind')
    op.drop_table('job_search_preferences')
