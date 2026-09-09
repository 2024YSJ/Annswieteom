from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Index, JSON, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

FEED_SOURCES = ("worknet", "youthcenter")

#: 피드를 두 갈래로 나누는 축. 메인 화면이 "맞춤 취업처"와 "지원 정책" 두 섹션으로
#: 갈리므로 파생값이 아니라 실제 컬럼으로 둔다 — 프론트가 섹션마다 독립된 요청을
#: 보내고 각자 자기 풀 안에서만 정렬되게 하려면 인덱스가 걸린 필터가 필요하다.
FEED_KINDS = ("job", "policy")

#: 워크넷 6개 카테고리(job_info_client.CATEGORY_LABELS와 같은 키) + 온통청년 1개.
#: 훈련과정과 구직자취업역량강화프로그램을 "policy"로 보내는 게 중요하다 —
#: 온통청년 인증키는 담당자 심사를 거쳐야 나오는데(워크넷 키들이 그랬듯) 제때
#: 안 나올 수 있고, 그때도 지원 정책 섹션이 비지 않아야 한다. 둘 다 실제로
#: 정부 지원 프로그램이 맞으므로 억지 분류도 아니다.
FEED_KIND_BY_CATEGORY = {
    "job_fair": "job",
    "public_recruitment": "job",
    "public_recruitment_company": "job",
    "promising_sme": "job",
    "training_course": "policy",
    "job_seeker_program": "policy",
    "youth_policy": "policy",
}

FEED_CATEGORIES = tuple(FEED_KIND_BY_CATEGORY)


class FeedItem(Base):
    """외부 API에서 긁어와 캐시해 둔 공고/정책 한 건. 전 사용자 공용이다 —
    같은 공고는 누구에게나 같은 항목이고, 사용자마다 다른 건 정렬 순서뿐이다.

    **벡터 컬럼이 여기 없는 건 의도적이다.** pgvector의 Vector 타입은 SQLite
    컴파일러가 없어서, 이 테이블에 벡터를 얹으면 tests/api/conftest.py가
    Base.metadata.create_all로 이 테이블을 만들 수 없고 피드 API 전체가 API
    레이어에서 테스트 불가능해진다(record_chunks가 대부분의 픽스처에서 빠져
    있는 이유와 같다). 벡터는 feed_item_embeddings에 1:1로 따로 둔다.
    """

    __tablename__ = "feed_items"
    __table_args__ = (
        CheckConstraint(f"source IN {FEED_SOURCES}", name="ck_feed_items_source"),
        CheckConstraint(f"feed_kind IN {FEED_KINDS}", name="ck_feed_items_feed_kind"),
        CheckConstraint(f"category IN {FEED_CATEGORIES}", name="ck_feed_items_category"),
        UniqueConstraint("source", "category", "dedup_key", name="uq_feed_items_identity"),
        Index("ix_feed_items_active_recent", "is_active", "feed_kind", "first_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    feed_kind: Mapped[str] = mapped_column(Text, nullable=False)
    # 소스가 안정적인 id를 주면 "k:<id>", 아니면 제목+부제+메타의 sha256("h:...").
    # services/feed/dedup.py 참고.
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # generated_sentences.evidence_fact_ids / interview_answers.confirmed_facts와
    # 같은 이유로 JSONB가 아닌 제네릭 JSON.
    meta_lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    detail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 소스가 등록일/게시일을 주는 경우에만 채워진다. 워크넷 6개 중 대부분은 안 준다.
    source_published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 실제로 임베딩에 넣은 문자열을 그대로 보관한다 — 다음 수집 때 "이 항목을 다시
    # 임베딩해야 하나"를 문자열 비교 한 번으로 끝내기 위해서.
    embed_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 최신순 정렬의 기준. source_published_at이 아니라 이걸 쓰는 이유는 4개
    # 카테고리가 아예 날짜를 안 주기 때문이고, "우리가 처음 본 시각"은 재수집해도
    # 안 바뀌어서 게시판 정렬 키로 안정적이다.
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 소스 목록에서 사라진 항목은 지우지 않고 비활성으로 둔다 — id 없는 카테고리는
    # 문구가 조금 바뀌면 새 행으로 들어오는데, 옛 행을 즉시 삭제하면 잠깐이라도
    # 사라졌던 항목이 영영 없어진다.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
