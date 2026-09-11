"""add activity_categories.draft_turns (category-level fact review)

Revision ID: c7d1e5a9f2b4
Revises: b8e4d2a6c1f9
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7d1e5a9f2b4'
down_revision: Union[str, Sequence[str], None] = 'b8e4d2a6c1f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """카테고리 단위 확인을 위한 초안 저장소.

    지금까지는 답변마다 AI가 뽑은 사실 카드를 사용자가 바로 확인해야 다음 질문이
    나왔다 — 카테고리 하나에 확인을 열 번 가까이 누르게 돼 번거로웠다(2026-09-11
    요청). 이제 답변에서 뽑은 사실은 이 컬럼에 "아직 확인 전 초안"으로 쌓이고,
    카테고리 질문이 끝날 때 한 번에 확인받아 confirmed_facts로 옮겨진다.

    sessions.pending_turn에 싣지 않은 이유: 그 값은 질문마다 통째로 교체되고,
    커버리지 채우기·소분류 확인 등 여러 경로가 None으로 비워 초안이 조용히 사라진다.
    초안은 그 초안이 속한 카테고리에 둔다. 확인이 끝나면 다시 NULL이 된다.
    """
    op.add_column('activity_categories', sa.Column('draft_turns', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('activity_categories', 'draft_turns')
