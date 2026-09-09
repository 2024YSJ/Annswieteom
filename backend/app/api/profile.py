from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.interview_answer import InterviewAnswer
from app.models.user import User
from app.schemas.profile import ArchivedAnswerRead, ArchiveSummaryRead

router = APIRouter(prefix="/me", tags=["profile"])


def _require_registered(user: User) -> None:
    """문답 아카이브는 이메일로 등록된 계정에만 열어준다.

    게스트 계정은 세션을 하나만 가질 수 있어서(app/api/sessions.py의
    guest_session_limit_reached) 애초에 "세션을 넘어 쌓인 기록"이라는 게
    성립하지 않는다. 기록 자체는 게스트 세션에서도 user_id를 달고 저장되고,
    게스트가 이메일로 회원가입하면 같은 user 행이 승격되므로(app/api/auth.py)
    그 시점부터 여기서 그대로 보인다 — 승격 과정에서 잃는 것은 없다.
    """
    if user.is_guest:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registered_account_required")


@router.get("/answers", response_model=list[ArchivedAnswerRead])
async def list_archived_answers(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category_type: str | None = None,
    exclude_session_id: uuid.UUID | None = None,
    confirmed_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InterviewAnswer]:
    """이 계정에 쌓인 문답 기록, 최신순.

    `exclude_session_id`는 "지금 진행 중인 세션 말고, 예전에 뭐라고 답했더라"를
    보여주기 위한 것이다 — 새 세션이 늘 백지에서 시작하던 이유가 바로 이 조회
    경로가 없어서였다. 여기서 제안된 내용도 결국 인터뷰의 확인 단계를 다시
    거치므로 정직성 가드레일은 그대로다.
    """
    _require_registered(current_user)

    stmt = select(InterviewAnswer).where(InterviewAnswer.user_id == current_user.id)
    if category_type is not None:
        stmt = stmt.where(InterviewAnswer.category_type == category_type)
    if exclude_session_id is not None:
        # session_id IS NULL(원본 세션이 삭제된 기록)은 남겨야 한다 — SQL의
        # `!=`는 NULL을 걸러버리므로 명시적으로 OR로 살린다.
        stmt = stmt.where(
            (InterviewAnswer.session_id.is_(None)) | (InterviewAnswer.session_id != exclude_session_id)
        )
    if confirmed_only:
        # 답변만 하고 확인 단계에서 이탈한 턴은 confirmed_facts가 빈 배열로 남는다.
        stmt = stmt.where(InterviewAnswer.confirmed_facts != [])

    stmt = stmt.order_by(InterviewAnswer.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/answers/summary", response_model=ArchiveSummaryRead)
async def get_archive_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArchiveSummaryRead:
    _require_registered(current_user)

    total_answers = await db.scalar(
        select(func.count()).select_from(InterviewAnswer).where(InterviewAnswer.user_id == current_user.id)
    )
    rows = list(
        (
            await db.execute(
                select(InterviewAnswer.category_type, InterviewAnswer.confirmed_facts).where(
                    InterviewAnswer.user_id == current_user.id
                )
            )
        ).all()
    )
    return ArchiveSummaryRead(
        total_answers=total_answers or 0,
        total_confirmed_facts=sum(len(facts or []) for _, facts in rows),
        category_types=sorted({category_type for category_type, _ in rows}),
    )


@router.delete("/answers/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_archived_answer(
    answer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """아카이브에서 한 건을 지운다 — 답변 원문이 계정에 계속 남는 이상,
    지울 방법도 같이 있어야 한다.

    No `-> None` annotation — 204 응답 본문 assertion 때문(sessions.delete_session 주석 참고).
    """
    _require_registered(current_user)

    answer = await db.get(InterviewAnswer, answer_id)
    if answer is None or answer.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="answer_not_found")
    await db.delete(answer)
    await db.commit()
