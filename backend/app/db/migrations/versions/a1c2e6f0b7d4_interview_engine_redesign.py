"""interview engine redesign: collapse session statuses, widen fact_type, pending_turn

The interview flow moved from a fixed 3-question-per-category state machine
(FREQ/TASK/ACHIEVEMENT x DRAFT/CONFIRM) to an agentic loop where a category's
progress is derived from ActivityCategory/ConfirmedFact data rather than
encoded in session.status. See docs/architecture.md and
app/services/interview_orchestrator.py / app/services/interview_question_bank.py.

Revision ID: a1c2e6f0b7d4
Revises: 147d9ab2f4bf
Create Date: 2026-09-04 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c2e6f0b7d4'
down_revision: Union[str, Sequence[str], None] = '147d9ab2f4bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_SESSION_STATUSES = (
    "('PERIOD_INPUT', 'CATEGORY_SELECT', 'RECORD_UPLOAD', 'FREQ_DRAFT', 'FREQ_CONFIRM', "
    "'TASK_DRAFT', 'TASK_CONFIRM', 'ACHIEVEMENT_DRAFT', 'ACHIEVEMENT_CONFIRM', "
    "'RESULT_GENERATE', 'RESULT_REVIEW')"
)
NEW_SESSION_STATUSES = (
    "('PERIOD_INPUT', 'CATEGORY_SELECT', 'RECORD_UPLOAD', 'INTERVIEWING', "
    "'RESULT_GENERATE', 'RESULT_REVIEW')"
)
# Superset of old+new, used only as a transient constraint while in-flight
# rows are updated from an old value to 'INTERVIEWING' — a plain
# create_check_constraint validates every existing row immediately, so the
# final (new-only) constraint can't be installed until no row holds an old
# per-category value anymore.
TRANSITIONAL_SESSION_STATUSES = (
    "('PERIOD_INPUT', 'CATEGORY_SELECT', 'RECORD_UPLOAD', 'FREQ_DRAFT', 'FREQ_CONFIRM', "
    "'TASK_DRAFT', 'TASK_CONFIRM', 'ACHIEVEMENT_DRAFT', 'ACHIEVEMENT_CONFIRM', "
    "'INTERVIEWING', 'RESULT_GENERATE', 'RESULT_REVIEW')"
)

OLD_FACT_TYPES = "('frequency', 'task', 'achievement')"
NEW_FACT_TYPES = (
    "('frequency', 'task', 'achievement', 'hardship_and_coping', 'motivation', "
    "'study_method', 'study_goal', 'role_and_responsibility', 'outcome', 'context', 'followup')"
)


def upgrade() -> None:
    # 1. Swap in a transitional constraint (old values + INTERVIEWING) first —
    #    Postgres validates every existing row against a freshly-created CHECK
    #    constraint immediately, so jumping straight to the new-only
    #    constraint would itself fail on any row still sitting at an old
    #    per-category value. With the transitional constraint in place, any
    #    session still mid-interview under the old 6-state vocabulary can be
    #    updated to INTERVIEWING; its per-category progress is re-derivable
    #    from ConfirmedFact rows already present (next_base_question), so no
    #    data is lost — just the fine-grained DRAFT/CONFIRM sub-state. Only
    #    then is the final, narrower constraint installed (safe at that point
    #    since no row holds an old value anymore).
    op.drop_constraint('ck_sessions_status', 'sessions', type_='check')
    op.create_check_constraint('ck_sessions_status', 'sessions', f"status IN {TRANSITIONAL_SESSION_STATUSES}")
    op.execute(
        "UPDATE sessions SET status = 'INTERVIEWING' WHERE status IN "
        "('FREQ_DRAFT', 'FREQ_CONFIRM', 'TASK_DRAFT', 'TASK_CONFIRM', "
        "'ACHIEVEMENT_DRAFT', 'ACHIEVEMENT_CONFIRM')"
    )
    op.drop_constraint('ck_sessions_status', 'sessions', type_='check')
    op.create_check_constraint('ck_sessions_status', 'sessions', f"status IN {NEW_SESSION_STATUSES}")

    # 2. pending_draft's old shape (a single draft_text string) is incompatible
    #    with pending_turn's new shape (question + N candidate facts). Any
    #    in-flight draft is an abandoned/incomplete turn either way, so it's
    #    safe to discard rather than migrate its shape.
    op.execute("UPDATE sessions SET pending_draft = NULL")
    op.alter_column('sessions', 'pending_draft', new_column_name='pending_turn')

    # 3. Fact type CHECK widened — old values remain valid members of the new
    #    set, so existing rows need no data backfill.
    op.drop_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', type_='check')
    op.create_check_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', f"fact_type IN {NEW_FACT_TYPES}")

    # 4. New column, nullable — pre-migration rows have no recorded question text.
    op.add_column('confirmed_facts', sa.Column('source_question_text', sa.Text(), nullable=True))


def downgrade() -> None:
    # Lossy/best-effort, same convention as 90edf5d28f6a's downgrade: only
    # safe if no row currently uses INTERVIEWING or a new fact_type value.
    op.drop_column('confirmed_facts', 'source_question_text')

    op.drop_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', type_='check')
    op.create_check_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', f"fact_type IN {OLD_FACT_TYPES}")

    op.alter_column('sessions', 'pending_turn', new_column_name='pending_draft')

    op.drop_constraint('ck_sessions_status', 'sessions', type_='check')
    op.create_check_constraint('ck_sessions_status', 'sessions', f"status IN {OLD_SESSION_STATUSES}")
    op.execute("UPDATE sessions SET status = 'FREQ_DRAFT' WHERE status = 'INTERVIEWING'")
