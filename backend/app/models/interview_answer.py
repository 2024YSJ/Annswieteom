from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class InterviewAnswer(Base):
    """계정 단위로 축적되는 문답 기록 — 질문 하나와 그 답변 원문.

    두 가지를 동시에 해결한다.

    1) **원문이 어디에도 남지 않던 문제**: 인터뷰 답변은 extract_facts를 거쳐
       짧은 사실 문장으로 요약된 뒤 confirmed_facts에만 저장됐고, 사용자가 실제로
       타이핑한 문장은 pending_turn을 스쳐 지나가고 사라졌다. 요약 과정에서 잘려
       나간 뉘앙스를 나중에 되살릴 방법이 없었다.
    2) **세션을 넘어 쌓이지 않던 문제**: confirmed_facts는 category → session에
       매달려 있어 세션을 지우면 같이 사라지고, 새 세션은 늘 백지에서 시작했다.
       이 테이블은 user_id에 직접 매달리고 session_id는 SET NULL이라, 세션이
       사라져도 그 계정의 문답 기록은 남는다.

    게스트도 user 행을 갖기 때문에 게스트 세션에서도 기록되고, 게스트가
    이메일로 회원가입하면 같은 user 행의 is_guest만 False로 바뀌므로
    (app/api/auth.py의 게스트 승격) 기록이 그대로 이메일 계정으로 이어진다.

    **정직성 가드레일**: 이 테이블은 문서 생성 입력이 될 수 없다. 생성 함수는
    여전히 confirmed_facts만 받는다(app/services/document_generator.py). 여기
    저장된 답변 원문은 사용자에게 되돌려 보여주거나 다음 세션에서 "예전에 이렇게
    답하셨어요"라고 제안하기 위한 것이고, 제안은 언제나 확인 단계를 다시 거친다.
    """

    __tablename__ = "interview_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    # 카테고리는 스냅샷으로만 들고 있는다(FK 아님) — 세션이 지워지면 카테고리 행도
    # CASCADE로 사라지는데, 그 뒤에도 "무슨 활동에 대한 문답이었는지"는 읽을 수
    # 있어야 한다.
    category_label: Mapped[str] = mapped_column(Text, nullable=False)
    category_type: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_source: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 확정 단계에서 이 답변으로부터 실제로 확정된 사실들의 스냅샷:
    # [{"content": ..., "fact_type": ..., "source_type": ...}]. 확정 전에는 빈 배열
    # (답변만 하고 확인을 안 누른 채 이탈한 경우가 그대로 구분된다). generated_sentences.
    # evidence_fact_ids와 같은 이유로 JSONB가 아닌 제네릭 JSON을 쓴다.
    confirmed_facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")
    session: Mapped["Session | None"] = relationship("Session", back_populates="interview_answers")
