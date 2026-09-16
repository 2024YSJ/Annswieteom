"""widen activity_categories.category_type to include internship, club

A 3-month internship was getting the part_time question bank ("이 아르바이트를
얼마나 자주...") and a casual book club was getting the study question bank
("무엇을 목표로 공부/자격증 준비를...") — neither of the old 8 types fit either
pattern well, confirmed in the 6-persona live verification round (2026-09-17).

Revision ID: b7e2f4a9c1d5
Revises: d2a6f19e4b73
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b7e2f4a9c1d5'
down_revision: Union[str, Sequence[str], None] = 'd2a6f19e4b73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_CATEGORY_TYPES = (
    "part_time", "freelance", "volunteer", "study",
    "project", "caregiving", "travel", "other",
)
NEW_CATEGORY_TYPES = (
    "part_time", "freelance", "volunteer", "study",
    "project", "caregiving", "travel", "internship", "club", "other",
)


def upgrade() -> None:
    op.drop_constraint('ck_activity_categories_type', 'activity_categories', type_='check')
    op.create_check_constraint('ck_activity_categories_type', 'activity_categories', f"category_type IN {NEW_CATEGORY_TYPES}")


def downgrade() -> None:
    # Safe only if no row currently uses "internship" or "club".
    op.drop_constraint('ck_activity_categories_type', 'activity_categories', type_='check')
    op.create_check_constraint('ck_activity_categories_type', 'activity_categories', f"category_type IN {OLD_CATEGORY_TYPES}")
