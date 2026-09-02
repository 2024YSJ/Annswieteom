"""fix session status values, add pending_draft

The original ck_sessions_status constraint used a status vocabulary
(INTERVIEW_FREQ/INTERVIEW_TASK/INTERVIEW_ACHIEVEMENT/GENERATING/DONE) that
never matched spec 8-2's actual state machine
(FREQ_DRAFT/FREQ_CONFIRM/.../RESULT_GENERATE/RESULT_REVIEW). Discovered while
implementing B-2 (interview state machine) — see
docs/checklists/person_B_frontend_backend/02_interview_state_machine_api.md.

Revision ID: 90edf5d28f6a
Revises: cf08f92b1e47
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '90edf5d28f6a'
down_revision: Union[str, Sequence[str], None] = 'cf08f92b1e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUSES = "('PERIOD_INPUT', 'CATEGORY_SELECT', 'INTERVIEW_FREQ', 'INTERVIEW_TASK', 'INTERVIEW_ACHIEVEMENT', 'RECORD_UPLOAD', 'GENERATING', 'DONE')"
NEW_STATUSES = "('PERIOD_INPUT', 'CATEGORY_SELECT', 'RECORD_UPLOAD', 'FREQ_DRAFT', 'FREQ_CONFIRM', 'TASK_DRAFT', 'TASK_CONFIRM', 'ACHIEVEMENT_DRAFT', 'ACHIEVEMENT_CONFIRM', 'RESULT_GENERATE', 'RESULT_REVIEW')"


def upgrade() -> None:
    op.drop_constraint('ck_sessions_status', 'sessions', type_='check')
    op.create_check_constraint('ck_sessions_status', 'sessions', f"status IN {NEW_STATUSES}")
    op.add_column('sessions', sa.Column('pending_draft', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('sessions', 'pending_draft')
    op.drop_constraint('ck_sessions_status', 'sessions', type_='check')
    op.create_check_constraint('ck_sessions_status', 'sessions', f"status IN {OLD_STATUSES}")
