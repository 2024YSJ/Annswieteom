# -*- coding: utf-8 -*-
"""원클릭 데모 모드(GET /api/v1/demo/document)가 노출할 세션 하나를 만든다.

    cd backend && python scripts/seed_demo_session.py [--reset]

실제 LLM/임베딩 서버 없이 ORM으로 직접 확정된(FINAL) 문서까지 채운다 — 발표
직전 Ollama가 안 떠 있어서 데모 세션을 못 만드는 리스크를 피하고, 스코어보드
숫자가 매번 똑같이 나오게 하기 위해서다(실제 생성 파이프라인 검증은
backend/tests/api/test_document.py 등 기존 통합 테스트가 담당한다).

일부러 근거 없는 문장을 하나 섞어 둔다 — 정직성 가드레일이 이런 문장을 숨기지
않고 "· 인용된 근거 없음" 배지로 그대로 드러낸다는 것 자체가 보여줄 가치가
있다.

출력된 UUID를 DEMO_SESSION_ID(backend/.env, 또는 배포 환경변수)에 붙여넣는다.
--reset은 이전 실행이 .demo_session_id에 남겨둔 세션(과 그 소유자 계정)을
먼저 지운다.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal
from app.models.activity_category import ActivityCategory
from app.models.confirmed_fact import ConfirmedFact
from app.models.gap_period import GapPeriod
from app.models.generated_document import GeneratedDocument
from app.models.generated_paragraph import GeneratedParagraph
from app.models.generated_sentence import GeneratedSentence
from app.models.record import Record
from app.models.record_chunk import RecordChunk
from app.models.session import Session as SessionModel
from app.models.user import User

_STATE_FILE = Path(__file__).parent / ".demo_session_id"


async def _delete_previous() -> None:
    if not _STATE_FILE.exists():
        return
    prev_id_text = _STATE_FILE.read_text().strip()
    if not prev_id_text:
        return
    async with AsyncSessionLocal() as db:
        try:
            session = await db.get(SessionModel, uuid.UUID(prev_id_text))
        except ValueError:
            return
        if session is None:
            return
        # User -> sessions -> {gap_period, categories, records, documents}는 전부
        # ON DELETE CASCADE(models/user.py, models/session.py) — 유저 하나만 지우면
        # 데모 세션의 데이터 전체가 함께 정리된다.
        user = await db.get(User, session.user_id)
        if user is not None:
            await db.delete(user)
        else:
            await db.delete(session)
        await db.commit()


async def _seed() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        user = User(nickname="데모 계정", is_guest=True)
        db.add(user)
        await db.flush()

        session = SessionModel(
            user_id=user.id, kind="gap_fill", status="RESULT_REVIEW", title="데모: 6개월 공백기"
        )
        db.add(session)
        await db.flush()

        db.add(GapPeriod(session_id=session.id, start_date=date(2025, 1, 1), end_date=date(2025, 6, 30)))

        part_time = ActivityCategory(
            session_id=session.id, category_type="part_time", order_index=0, status="DONE",
            period_start=date(2025, 1, 6), period_end=date(2025, 3, 31), period_source="user_set",
        )
        study = ActivityCategory(
            session_id=session.id, category_type="study", order_index=1, status="DONE",
            period_start=date(2025, 2, 1), period_end=date(2025, 5, 31), period_source="user_set",
        )
        project = ActivityCategory(
            session_id=session.id, category_type="project", order_index=2, status="DONE",
            period_start=date(2025, 4, 1), period_end=date(2025, 6, 30), period_source="user_set",
        )
        db.add_all([part_time, study, project])
        await db.flush()

        # study 카테고리의 근거 기록물(블로그) — record_cited 사실 하나가 이걸 인용한다.
        record = Record(
            session_id=session.id, category_id=study.id, record_type="blog_url",
            source_url="https://example-blog.tistory.com/42", platform="tistory", parse_status="DONE",
            raw_text="정보처리기사 필기 합격 후기 - 3개월간 매일 인강 2시간씩 들었습니다.",
        )
        db.add(record)
        await db.flush()
        chunk = RecordChunk(
            record_id=record.id, chunk_index=0, published_at=date(2025, 4, 20),
            chunk_text="정보처리기사 필기 합격 후기 - 3개월간 매일 인강 2시간씩 들었습니다.",
        )
        db.add(chunk)
        await db.flush()

        def make_fact(category, fact_type, content, source_type, ai_draft_text=None, source_chunk=None):
            f = ConfirmedFact(
                category_id=category.id, fact_type=fact_type, content=content, source_type=source_type,
                source_record_chunk_id=source_chunk.id if source_chunk else None, ai_draft_text=ai_draft_text,
            )
            db.add(f)
            return f

        # part_time: 하나는 AI 초안 그대로 수용, 하나는 사용자가 고쳐 씀
        f1 = make_fact(part_time, "frequency", "주 4회, 하루 6시간씩 편의점에서 근무했다",
                        "user_confirmed", ai_draft_text="주 4회, 하루 6시간씩 편의점에서 근무했다")
        f2 = make_fact(part_time, "task", "재고 관리와 발주 업무를 맡아 처리했다",
                        "user_edited", ai_draft_text="계산대 업무를 했다")

        # study: 기록물(블로그)로 뒷받침되는 사실 + 그대로 수용된 사실
        f3 = make_fact(study, "achievement", "정보처리기사 필기 시험에 합격했다",
                        "record_cited", ai_draft_text="정보처리기사 필기 시험에 합격했다", source_chunk=chunk)
        f4 = make_fact(study, "frequency", "3개월간 매일 2시간씩 인터넷 강의를 들었다",
                        "user_confirmed", ai_draft_text="3개월간 매일 2시간씩 인터넷 강의를 들었다")

        # project: 사용자가 직접 고친 사실 하나
        f5 = make_fact(project, "outcome", "혼자서 개인 웹 프로젝트를 기획부터 배포까지 완성했다",
                        "user_edited", ai_draft_text="웹 프로젝트를 진행했다")

        await db.flush()

        document = GeneratedDocument(session_id=session.id, tone="neutral", version=1, status="FINAL")
        db.add(document)
        await db.flush()

        p1 = GeneratedParagraph(document_id=document.id, order_index=0, topic="편의점 아르바이트", user_confirmed=True)
        p2 = GeneratedParagraph(document_id=document.id, order_index=1, topic="자격증 준비와 학습", user_confirmed=True)
        p3 = GeneratedParagraph(document_id=document.id, order_index=2, topic="개인 프로젝트 진행", user_confirmed=True)
        db.add_all([p1, p2, p3])
        await db.flush()

        def make_sentence(paragraph, category, order_index, text, cited_facts, *, edited=False, unsupported=False):
            db.add(GeneratedSentence(
                document_id=document.id,
                category_id=category.id,
                paragraph_id=paragraph.id,
                order_index=order_index,
                text=text,
                evidence_fact_ids=[str(f.id) for f in cited_facts],
                consistency_check_passed=not unsupported,
                consistency_score=None if unsupported else 0.91,
                edited_by_user=edited,
            ))

        make_sentence(p1, part_time, 0, "공백 기간 동안 편의점에서 주 4회, 하루 6시간씩 근무하며 매장을 운영했다.", [f1])
        make_sentence(p1, part_time, 1, "재고 관리와 발주 업무를 직접 맡아 처리하며 매장 운영 전반을 경험했다.", [f2], edited=True)
        make_sentence(p2, study, 2, "3개월간 매일 2시간씩 인터넷 강의를 들으며 정보처리기사 시험을 준비했다.", [f4])
        make_sentence(p2, study, 3, "그 결과 정보처리기사 필기 시험에 합격했다.", [f3])
        make_sentence(p3, project, 4, "혼자서 개인 웹 프로젝트를 기획부터 배포까지 완성했다.", [f5], edited=True)
        make_sentence(p3, project, 5, "이 기간 동안 다양한 사이드 프로젝트에 참여하며 실력을 키웠다.", [], unsupported=True)

        await db.commit()
        await db.refresh(session)
        return session.id


async def _main(reset: bool) -> None:
    if reset:
        await _delete_previous()
    session_id = await _seed()
    _STATE_FILE.write_text(str(session_id))
    print(session_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="이전 데모 세션(과 소유 계정)을 먼저 삭제한다")
    args = parser.parse_args()
    asyncio.run(_main(args.reset))
