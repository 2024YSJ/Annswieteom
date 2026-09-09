"""per-account interview answer log + activity period columns + sentence consistency score

Revision ID: d8c1b4a70f22
Revises: 735683a2d64a
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8c1b4a70f22'
down_revision: Union[str, Sequence[str], None] = '735683a2d64a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """세 가지 구조적 공백을 메운다.

    0) interview_answers — 계정 단위 문답 기록. 사용자가 실제로 타이핑한 답변
       원문은 지금까지 어디에도 저장되지 않았고(extract_facts로 요약된 결과만
       confirmed_facts에 남았다), confirmed_facts는 세션에 매달려 있어 세션을
       지우면 사라졌다. 이 테이블은 user_id에 직접 매달리고 session_id는
       SET NULL이라 계정에 계속 쌓인다.
    1) activity_categories에 기간(period_start/period_end/period_source) — 이게
       없어서 "공백기 채우기" 서비스가 정작 공백기가 얼마나 채워졌는지 계산할 수
       없었다. gap_periods에는 전체 시작/끝만 있고 활동 쪽에는 날짜가 없었다.
       period_source는 이 값을 LLM이 유추했는지 사용자가 직접 넣었는지 구분한다
       (둘 다 confirmed_facts가 아니므로 생성 문서에 인용되지 않는다).
    2) generated_sentences에 consistency_score/edited_by_user — 정합성 검사가
       bool만 남기고 실제 유사도를 버려서 임계값을 조정할 근거가 없었고,
       사용자가 직접 고쳐 쓴 문장과 임베딩 검증을 통과한 문장이 같은 true로
       뭉개져 있었다.
    """
    op.create_table(
        'interview_answers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=True),
        sa.Column('category_label', sa.Text(), nullable=False),
        sa.Column('category_type', sa.Text(), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('question_source', sa.Text(), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=False),
        sa.Column('confirmed_facts', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_interview_answers_user_id', 'interview_answers', ['user_id'])

    op.add_column('activity_categories', sa.Column('period_start', sa.Date(), nullable=True))
    op.add_column('activity_categories', sa.Column('period_end', sa.Date(), nullable=True))
    op.add_column('activity_categories', sa.Column('period_source', sa.String(length=20), nullable=True))
    op.create_check_constraint(
        'ck_activity_categories_period_source',
        'activity_categories',
        "period_source IN ('ai_inferred', 'user_set')",
    )

    op.add_column('generated_sentences', sa.Column('consistency_score', sa.Float(), nullable=True))
    op.add_column(
        'generated_sentences',
        sa.Column('edited_by_user', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # server_default는 기존 행을 채우기 위한 것뿐 — 앞으로의 INSERT는 ORM 기본값이
    # 담당하므로 제약을 남겨둘 이유가 없다.
    op.alter_column('generated_sentences', 'edited_by_user', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('generated_sentences', 'edited_by_user')
    op.drop_column('generated_sentences', 'consistency_score')
    op.drop_constraint('ck_activity_categories_period_source', 'activity_categories', type_='check')
    op.drop_column('activity_categories', 'period_source')
    op.drop_column('activity_categories', 'period_end')
    op.drop_column('activity_categories', 'period_start')
    op.drop_index('ix_interview_answers_user_id', table_name='interview_answers')
    op.drop_table('interview_answers')
