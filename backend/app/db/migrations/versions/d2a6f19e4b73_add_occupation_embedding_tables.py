"""add occupation embedding tables (job/training/policy occupation matching)

Revision ID: d2a6f19e4b73
Revises: c7d1e5a9f2b4
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2a6f19e4b73'
down_revision: Union[str, Sequence[str], None] = 'c7d1e5a9f2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """직무 관련성 전용 벡터 2개 — feed_item_embeddings/user_profile_embeddings
    (e7a1c93d5b20)와 같은 1:1 곁테이블 패턴. 이유도 같다: pgvector Vector가
    SQLite에 없어 본체에 얹으면 피드 API 테스트가 불가능해진다.

    feed_item_occupation_embeddings는 title만 임베딩한다(embed_text 전체가
    아니라) — 지역/회사명/날짜 같은 메타 텍스트가 직무 신호를 희석해서다.
    feed_kind(job/policy)와 무관하게 전체 feed_items에 채운다 — 채용공고·
    훈련과정·온통청년 정책 세 화면이 이 한 테이블을 공유한다.

    user_occupation_embeddings는 UserProfileEmbedding류의
    fingerprint/answer_count/latest_answer_at을 두지 않는다 — 원본이
    desired_job 한 줄짜리 문자열이라 source_text 등가 비교로 충분하다
    (과설계 방지, services/feed/occupation_adapter.py).

    ivfflat 인덱스는 두 벡터 컬럼 다 만들지 않는다 — e7a1c93d5b20과 같은 이유
    (현재 행 수 규모에서는 seq scan이 더 빠르고, 필요해지면
    cf08f92b1e47_init_schema.py:129 형태로 나중에 추가).
    """
    op.create_table(
        'feed_item_occupation_embeddings',
        sa.Column('feed_item_id', sa.UUID(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column('embedding_model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['feed_item_id'], ['feed_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('feed_item_id'),
    )

    op.create_table(
        'user_occupation_embeddings',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column('embedding_model', sa.Text(), nullable=True),
        sa.Column('source_text', sa.Text(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_occupation_embeddings')
    op.drop_table('feed_item_occupation_embeddings')
