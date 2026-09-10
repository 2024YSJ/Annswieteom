"""add user_attributes, user_consents, feed_items.eligibility

Revision ID: b8e4d2a6c1f9
Revises: f3b6d0c8a114
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8e4d2a6c1f9'
down_revision: Union[str, Sequence[str], None] = 'f3b6d0c8a114'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEYS = (
    'birth_year', 'residence_region', 'desired_region', 'education_level', 'major_field',
    'employment_status', 'desired_job', 'desired_employment_type', 'skills', 'certificates',
    'interests', 'annual_income', 'special_groups', 'marital_status',
)


def upgrade() -> None:
    """대화로 알게 된 사람 단위 속성 + 민감정보 동의 + 정책 자격조건.

    지금까지 인터뷰는 **활동 사실**(confirmed_facts)만 저장했고 나이·거주지·학력·
    희망직무 같은 속성은 어디에도 남지 않았다. 추천은 프로필 텍스트 한 덩어리를
    벡터 하나로 만들어 코사인 정렬만 했기 때문에 "모든 조건이 맞는 정책(교집합)을
    먼저"라는 요구를 표현할 방법이 없었다(2026-09-11 요청).

    - user_attributes: 속성 한 값 = 한 행. 바뀌면 옛 행에 invalidated_at을 찍고
      새 행을 넣어 이력을 남긴다. 사용자가 지운 값은 status='rejected'로 남겨
      다음 대화에서 같은 값이 다시 추출돼도 되살리지 않는다.
    - user_consents: 소득·특화분야(장애·수급·한부모)·혼인은 동의가 있어야 저장한다.
    - feed_items.eligibility: 온통청년 응답의 자격조건 코드. 원래 받고 있었는데
      파서가 버리고 있었다.
    """
    op.create_table(
        'user_attributes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('value_norm', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='inferred'),
        sa.Column('sensitive', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('source_kind', sa.Text(), nullable=False),
        sa.Column('source_answer_id', sa.UUID(), nullable=True),
        sa.Column('evidence_text', sa.Text(), nullable=True),
        sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(f"key IN {_KEYS}", name='ck_user_attributes_key'),
        sa.CheckConstraint(
            "status IN ('inferred', 'confirmed', 'user_edited', 'rejected')", name='ck_user_attributes_status'
        ),
        sa.CheckConstraint(
            "source_kind IN ('interview_answer', 'job_search', 'wish_text', 'profile_form')",
            name='ck_user_attributes_source_kind',
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_answer_id'], ['interview_answers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_attributes_user_key', 'user_attributes', ['user_id', 'key'])

    op.create_table(
        'user_consents',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('consent_type', sa.Text(), nullable=False),
        sa.Column('granted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('granted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sensitive_mentioned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("consent_type IN ('sensitive_profiling')", name='ck_user_consents_type'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'consent_type'),
    )

    op.add_column('feed_items', sa.Column('eligibility', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('feed_items', 'eligibility')
    op.drop_table('user_consents')
    op.drop_index('ix_user_attributes_user_key', table_name='user_attributes')
    op.drop_table('user_attributes')
