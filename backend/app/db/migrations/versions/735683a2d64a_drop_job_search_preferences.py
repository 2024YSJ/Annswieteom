"""drop job_search_preferences (replaced by stateless job info search)

Revision ID: 735683a2d64a
Revises: a194faedf943
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '735683a2d64a'
down_revision: Union[str, Sequence[str], None] = 'a194faedf943'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """"일자리 찾기"를 turn-based 조건 입력에서 대화형 "취업 정보 종합 검색"으로
    전환하면서(devlog 16), 확정된 조건을 모아뒀다가 검색하던 방식 자체가
    없어졌다 — 매 질문이 그 자리에서 바로 검색으로 이어지는 무상태 대화라
    더 이상 저장할 "확정된 선호도"가 없다."""
    op.drop_table('job_search_preferences')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'job_search_preferences',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('desired_keyword', sa.String(length=200), nullable=True),
        sa.Column('desired_salary_min', sa.Integer(), nullable=True),
        sa.Column('desired_salary_max', sa.Integer(), nullable=True),
        sa.Column('desired_location', sa.String(length=200), nullable=True),
        sa.Column('education_level', sa.String(length=100), nullable=True),
        sa.Column('career_years', sa.Integer(), nullable=True),
        sa.Column('work_style_tags', sa.JSON(), nullable=False),
        sa.Column('completed_fields', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('free_text_notes', sa.Text(), nullable=True),
        sa.Column('last_searched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_results', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id'),
    )
