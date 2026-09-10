"""add user_preferences (user-editable 맞춤 정보)

Revision ID: f3b6d0c8a114
Revises: e7a1c93d5b20
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3b6d0c8a114'
down_revision: Union[str, Sequence[str], None] = 'e7a1c93d5b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """사용자가 직접 쓰는 "맞춤 정보"(희망사항) 저장소.

    맞춤 공고 정렬이 지금까지 interview_answers에서만 만들어져서, 공백기 정리를
    아직 안 한 사용자는 정렬을 조종할 수단이 전혀 없었다(2026-09-10 요청).

    user_profile_embeddings와 굳이 나눈 이유: 그쪽은 언제든 TRUNCATE 해도 지문
    메커니즘이 다시 채우는 파생 캐시지만, 이건 사용자가 직접 타이핑한 원본이라
    지우면 복구가 안 된다. 수명이 다른 데이터를 같은 테이블에 두지 않는다.
    """
    op.create_table(
        'user_preferences',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('wish_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_preferences')
