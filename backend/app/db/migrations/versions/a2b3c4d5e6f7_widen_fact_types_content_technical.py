"""widen confirmed_facts.fact_type to include content_application, technical_detail

New fixed base questions ask about the specific content learned/used and the
specific technical detail applied (2026-09-06 — questions were too shallow to
detect what a "study"/"project" activity actually involved).

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_FACT_TYPES = (
    "frequency", "task", "achievement",
    "hardship_and_coping", "motivation",
    "study_method", "study_goal",
    "role_and_responsibility", "outcome", "context",
    "followup",
)
NEW_FACT_TYPES = OLD_FACT_TYPES + ("content_application", "technical_detail")


def upgrade() -> None:
    op.drop_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', type_='check')
    op.create_check_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', f"fact_type IN {NEW_FACT_TYPES}")


def downgrade() -> None:
    # Safe only if no row currently uses a new fact_type value.
    op.drop_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', type_='check')
    op.create_check_constraint('ck_confirmed_facts_fact_type', 'confirmed_facts', f"fact_type IN {OLD_FACT_TYPES}")
