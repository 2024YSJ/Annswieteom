"""add feed tables (main-page job/policy feed)

Revision ID: e7a1c93d5b20
Revises: d8c1b4a70f22
Create Date: 2026-09-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e7a1c93d5b20'
down_revision: Union[str, Sequence[str], None] = 'd8c1b4a70f22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FEED_SOURCES = ("worknet", "youthcenter")
_FEED_KINDS = ("job", "policy")
_FEED_CATEGORIES = (
    "job_fair",
    "public_recruitment",
    "public_recruitment_company",
    "promising_sme",
    "training_course",
    "job_seeker_program",
    "youth_policy",
)


def upgrade() -> None:
    """메인 화면 피드(청년 지원 정책 / 공고 / 맞춤 공고)를 위한 테이블 4개.

    손으로 작성했다 — autogenerate는 이 저장소에서 매번 무관한 드리프트를
    끌고 오고(record_chunks의 ivfflat 인덱스를 introspect 못 함 등,
    4d7aacb4bfe8의 주석 참고) pgvector 컬럼도 깔끔하게 못 낸다.

    **벡터를 본체(feed_items)가 아니라 1:1 곁테이블에 둔 게 이 스키마의 핵심
    결정이다.** pgvector의 Vector 타입은 SQLite 컴파일러가 없어서, feed_items에
    벡터를 얹으면 tests/api/conftest.py가 그 테이블을 만들 수 없고 피드 API
    전체가 API 레이어에서 테스트 불가능해진다(record_chunks가 대부분의
    픽스처에서 빠져 있는 이유와 같다). 대가는 조인 하나와, 코사인 정렬 자체는
    자동 테스트로 못 덮는다는 점이다.

    ivfflat 인덱스는 **일부러 만들지 않았다.** 수백 행 규모에서는 seq scan보다
    느리고(lists 파라미터를 정하려면 데이터가 먼저 있어야 한다), 필요해지면
    cf08f92b1e47_init_schema.py:129와 같은 raw SQL 형태로 나중에 추가하면 된다.
    """
    op.create_table(
        'feed_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('feed_kind', sa.Text(), nullable=False),
        sa.Column('dedup_key', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('subtitle', sa.Text(), nullable=False, server_default=''),
        sa.Column('meta_lines', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('detail_url', sa.Text(), nullable=True),
        sa.Column('source_published_at', sa.Date(), nullable=True),
        sa.Column('embed_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'category', 'dedup_key', name='uq_feed_items_identity'),
        sa.CheckConstraint(f"source IN {_FEED_SOURCES}", name='ck_feed_items_source'),
        sa.CheckConstraint(f"feed_kind IN {_FEED_KINDS}", name='ck_feed_items_feed_kind'),
        sa.CheckConstraint(f"category IN {_FEED_CATEGORIES}", name='ck_feed_items_category'),
    )
    op.create_index('ix_feed_items_active_recent', 'feed_items', ['is_active', 'feed_kind', 'first_seen_at'])

    op.create_table(
        'feed_item_embeddings',
        sa.Column('feed_item_id', sa.UUID(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column('embedding_model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['feed_item_id'], ['feed_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('feed_item_id'),
    )

    op.create_table(
        'user_profile_embeddings',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column('embedding_model', sa.Text(), nullable=True),
        sa.Column('source_fingerprint', sa.Text(), nullable=True),
        sa.Column('source_answer_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source_latest_answer_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('profile_text', sa.Text(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )

    op.create_table(
        'feed_refresh_states',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('source_key', sa.Text(), nullable=False),
        sa.Column('last_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_succeeded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_key', name='uq_feed_refresh_states_source_key'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('feed_refresh_states')
    op.drop_table('user_profile_embeddings')
    op.drop_table('feed_item_embeddings')
    op.drop_index('ix_feed_items_active_recent', table_name='feed_items')
    op.drop_table('feed_items')
