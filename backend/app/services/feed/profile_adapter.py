from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.interview_answer import InterviewAnswer
from app.models.user_profile_embedding import UserProfileEmbedding
from app.services.embedding import LocalOllamaEmbedding

logger = logging.getLogger(__name__)

# ── 사용자 프로필 읽기 어댑터: 계약 ────────────────────────────────────────
#
# 이 모듈은 `interview_answers`(다른 작업이 만든 계정 단위 문답 아카이브)를
# 읽는 **저장소 전체에서 유일한 피드 쪽 지점**이다. 그 테이블은 우리 소유가
# 아니므로, 의존하는 컬럼을 여기 명시해 두고 바뀌면 이 파일만 고친다.
#
#   user_id / answer_text / category_label / confirmed_facts / created_at
#
# 이 다섯 개뿐이다. session_id, question_source, category_type, question_text에는
# 의존하지 않는다. confirmed_facts의 원소에 대해서도 `.get("content")` 하나만
# 가정한다. 테이블이 없거나 컬럼이 빠지면 예외를 내지 않고 빈 신호를 돌려준다 —
# 다른 팀의 스키마 변경이 메인 화면을 500으로 만들면 안 된다.
#
# GET /me/answers를 HTTP로 부르지 않고 DB를 직접 읽는 이유: 그 라우터는 게스트를
# 403으로 막고 페이지네이션/필터가 화면용으로 맞춰져 있어 랭킹 입력과 계약이
# 다르다. 자기 프로세스 안에서 자기 API를 HTTP로 호출하는 것도 피한다.
# ──────────────────────────────────────────────────────────────────────────

PROFILE_ANSWER_LIMIT = 30
PROFILE_TEXT_MAX_CHARS = 4000


@dataclass(frozen=True)
class ProfileSignal:
    text: str
    fingerprint: str
    answer_count: int
    latest_answer_at: datetime | None

    @property
    def is_empty(self) -> bool:
        return not self.text


_EMPTY = ProfileSignal(text="", fingerprint="", answer_count=0, latest_answer_at=None)


def _build_text(rows: list[InterviewAnswer]) -> str:
    """문답 행들을 임베딩에 넣을 한 덩어리 텍스트로.

    - **`question_text`는 일부러 뺀다.** 질문 은행이 만든 시스템 문구라 사용자
      간에 거의 동일하다. 넣으면 모든 프로필 벡터에 큰 공통 성분이 생겨 사용자
      사이 코사인 거리가 압착되고 개인화가 노이즈로 뭉개진다.
    - **확정되지 않은 답변도 넣는다.** 미확정이어도 사용자가 자기에 대해 실제로
      타이핑한 문장이라 랭킹 입력으로 유효하다. 정직성 가드레일은 "생성 문서가
      무엇을 인용할 수 있는가"를 규율하는 것이고(document_generator는 여전히
      confirmed_facts만 받는다), 어떤 공개 공고를 위로 올릴지는 그 대상이 아니다.
      피드는 문장을 만들지도 인용하지도 않는다.
    - **명시적 최신 가중치는 없다.** bge-m3가 패시지를 mean-pool하므로 가중치를
      주려면 벡터를 여러 개 만들어 합쳐야 하는데 지금 검증할 방법이 없다.
      최신순 30행 + 오래된 쪽부터 잘라내는 4000자 상한이 사실상의 가중치다.
    """
    blocks: list[str] = []
    for row in rows:
        lines = [f"[{row.category_label}] {row.answer_text}".strip()]
        for fact in row.confirmed_facts or []:
            content = fact.get("content") if isinstance(fact, dict) else None
            if content:
                lines.append(f"- {content}")
        blocks.append("\n".join(lines))

    # 오래된 블록부터 버린다(rows가 최신순이므로 뒤에서부터).
    text = ""
    for block in blocks:
        candidate = f"{text}\n\n{block}" if text else block
        if len(candidate) > PROFILE_TEXT_MAX_CHARS:
            break
        text = candidate
    return text.strip()


async def read_profile_signal(db: AsyncSession, user_id: uuid.UUID) -> ProfileSignal:
    try:
        rows = (
            await db.execute(
                select(InterviewAnswer)
                .where(InterviewAnswer.user_id == user_id)
                .order_by(InterviewAnswer.created_at.desc())
                .limit(PROFILE_ANSWER_LIMIT)
            )
        ).scalars().all()
    except Exception:
        # 테이블이 없거나(테스트 픽스처, 마이그레이션 이전) 스키마가 바뀐 경우.
        await db.rollback()
        logger.warning("feed: interview_answers unreadable; falling back to no profile", exc_info=True)
        return _EMPTY

    if not rows:
        return _EMPTY

    text = _build_text(list(rows))
    if not text:
        return _EMPTY
    return ProfileSignal(
        text=text,
        fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        answer_count=len(rows),
        latest_answer_at=rows[0].created_at,
    )


async def profile_counters(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, datetime | None]:
    """싼 1차 검사 — 인덱스 하나로 끝나는 COUNT/MAX. 읽기 경로가 매 요청마다
    프로필 텍스트를 다시 만들지 않게 해준다."""
    try:
        row = (
            await db.execute(
                select(func.count(InterviewAnswer.id), func.max(InterviewAnswer.created_at)).where(
                    InterviewAnswer.user_id == user_id
                )
            )
        ).one()
        return int(row[0] or 0), row[1]
    except Exception:
        await db.rollback()
        return 0, None


async def load_profile_vector(db: AsyncSession, user_id: uuid.UUID) -> list[float] | None:
    """저장된 프로필 벡터. 없거나 못 읽으면 None(= 비개인화 경로).

    벡터 테이블에는 pgvector 컬럼이 있어 SQLite에서는 아예 존재하지 않는다 —
    그 경우도 여기서 조용히 None이 된다.
    """
    try:
        row = await db.get(UserProfileEmbedding, user_id)
    except Exception:
        await db.rollback()
        return None
    return row.embedding if row is not None and row.embedding is not None else None


async def profile_needs_refresh(db: AsyncSession, user_id: uuid.UUID) -> bool:
    count, latest = await profile_counters(db, user_id)
    if count == 0:
        return False
    try:
        row = await db.get(UserProfileEmbedding, user_id)
    except Exception:
        # 벡터 테이블을 읽지 못했다(마이그레이션 이전, pgvector 없는 SQLite 등).
        # 문답은 쌓여 있는데 쓸 수 있는 벡터가 있다고 확인하지 못했으므로
        # "갱신 필요"로 본다 — 워커 자체가 실패에 관대해서(refresh_profile_embedding)
        # 헛도는 예약은 로그 한 줄로 끝나고, 원인이 고쳐지면 저절로 복구된다.
        # 반대로 False를 돌려주면 영구히 개인화가 안 켜진다.
        await db.rollback()
        return True
    if row is None or row.embedding is None:
        return True
    if row.source_answer_count != count:
        return True
    if latest is not None and row.source_latest_answer_at is not None:
        stored = row.source_latest_answer_at
        stored = stored if stored.tzinfo is not None else stored.replace(tzinfo=timezone.utc)
        current = latest if latest.tzinfo is not None else latest.replace(tzinfo=timezone.utc)
        return current > stored
    return latest is not None and row.source_latest_answer_at is None


async def refresh_profile_embedding(user_id: uuid.UUID) -> None:
    """백그라운드 워커 — 읽기 경로는 절대 이걸 기다리지 않는다.

    비용은 "새 문답 직후 딱 한 번 비개인화 응답"이고, 항목 쪽
    stale-while-revalidate와 같은 철학이다. 자기 세션을 연다.
    """
    async with AsyncSessionLocal() as db:
        signal = await read_profile_signal(db, user_id)
        if signal.is_empty:
            return

        row = await db.get(UserProfileEmbedding, user_id)
        if row is not None and row.source_fingerprint == signal.fingerprint and row.embedding is not None:
            # 내용이 그대로면 임베딩 호출 없이 카운터만 맞춰 둔다.
            row.source_answer_count = signal.answer_count
            row.source_latest_answer_at = signal.latest_answer_at
            await db.commit()
            return

        provider = LocalOllamaEmbedding()
        try:
            vectors = await provider.embed([signal.text])
        except Exception:
            # 아무것도 쓰지 않는다 — 다음 요청이 다시 시도하게 둔다.
            logger.warning("feed: profile embedding unavailable for %s", user_id, exc_info=True)
            return

        vector = vectors[0] if vectors else None
        if vector is None:
            return

        now = datetime.now(timezone.utc)
        if row is None:
            db.add(
                UserProfileEmbedding(
                    user_id=user_id,
                    embedding=vector,
                    embedding_model=provider.model_name,
                    source_fingerprint=signal.fingerprint,
                    source_answer_count=signal.answer_count,
                    source_latest_answer_at=signal.latest_answer_at,
                    profile_text=signal.text,
                    computed_at=now,
                )
            )
        else:
            row.embedding = vector
            row.embedding_model = provider.model_name
            row.source_fingerprint = signal.fingerprint
            row.source_answer_count = signal.answer_count
            row.source_latest_answer_at = signal.latest_answer_at
            row.profile_text = signal.text
            row.computed_at = now
        try:
            await db.commit()
        except Exception:
            # user_profile_embeddings가 없는 환경(SQLite 테스트)에서도
            # 조용히 넘어간다 — 이 함수는 부가 작업이지 요청 경로가 아니다.
            await db.rollback()


def get_profile_embedder():
    """FastAPI DI 훅. refresh_profile_embedding이 자기 세션을 열기 때문에
    get_db 오버라이드만으로는 테스트에서 못 바꾼다."""
    return refresh_profile_embedding


__all__ = [
    "PROFILE_ANSWER_LIMIT",
    "PROFILE_TEXT_MAX_CHARS",
    "ProfileSignal",
    "get_profile_embedder",
    "load_profile_vector",
    "profile_counters",
    "profile_needs_refresh",
    "read_profile_signal",
    "refresh_profile_embedding",
]
