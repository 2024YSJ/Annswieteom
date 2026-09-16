from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_owned_session
from app.db.session import get_db
from app.models.confirmed_fact import ConfirmedFact
from app.models.generated_document import GeneratedDocument
from app.models.generated_paragraph import GeneratedParagraph
from app.models.generated_sentence import GeneratedSentence
from app.models.session import Session as SessionModel
from app.schemas.document import (
    DocumentRead,
    DocumentVersionRead,
    FinalizeRequest,
    GenerateRequest,
    GpuGenerationStatsRead,
    MoveSentenceRequest,
    ParagraphRead,
    ParagraphUpdate,
    SentenceRead,
    SentenceUpdate,
    UnverifiedSentenceRead,
)
from app.schemas.share import ShareLinkRead
from app.services import document_generator
from app.services import interview_orchestrator as orchestrator
from app.services.document_assembly import build_document_read, build_paragraph_read, build_sentence_read, get_latest_document
from app.services.embedding import get_embedding_provider
from app.services.embedding.base import EmbeddingProvider
from app.services.llm.base import LLMProvider, LLMUnavailableError
from app.services.llm import get_llm_provider
from app.services.record_pipeline.citation import get_fact_citations

router = APIRouter(prefix="/sessions", tags=["document"])


def _violation_to_409(exc: orchestrator.StateMachineViolation) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _gpu_stats(llm: LLMProvider) -> GpuGenerationStatsRead | None:
    """방금 이 llm 인스턴스로 실행된 generate_document 호출들의 계측을 읽는다.

    document_generator.generate_full_document는 카테고리마다 llm.generate_document를
    한 번씩 순차 호출한다 — 그래서 문서 하나 생성에 여러 건이 쌓일 수 있고, 합쳐서
    하나의 tok/s로 보여준다. getattr로 접근하는 이유: FakeLLMProvider(테스트)에는
    이 속성이 없고, 그때는 그냥 배지를 안 보여주면 된다(None)."""
    calls = [s for s in getattr(llm, "generation_stats", []) if s.label == "generate_document"]
    if not calls:
        return None
    total_tokens = sum(c.out_tokens for c in calls)
    total_decode = sum(c.decode_seconds for c in calls)
    return GpuGenerationStatsRead(
        model=settings.local_llm_model_name,
        call_count=len(calls),
        total_output_tokens=total_tokens,
        tokens_per_second=(total_tokens / total_decode if total_decode else 0.0),
    )


# 이 셋은 이제 app/services/document_assembly.py로 옮겨졌다 — api/demo.py, api/share.py가
# 재사용한다. 이 파일은 그대로 alias해서 아래 호출부를 바꾸지 않는다.
_get_latest_document = get_latest_document
_sentence_read = build_sentence_read
_paragraph_read = build_paragraph_read
_document_read = build_document_read


async def _get_owned_sentence(session: SessionModel, sentence_id: uuid.UUID, db: AsyncSession) -> GeneratedSentence:
    stmt = (
        select(GeneratedSentence)
        .join(GeneratedDocument, GeneratedSentence.document_id == GeneratedDocument.id)
        .where(GeneratedSentence.id == sentence_id, GeneratedDocument.session_id == session.id)
    )
    sentence = (await db.execute(stmt)).scalar_one_or_none()
    if sentence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sentence_not_found")
    return sentence


async def _get_owned_paragraph(session: SessionModel, paragraph_id: uuid.UUID, db: AsyncSession) -> GeneratedParagraph:
    stmt = (
        select(GeneratedParagraph)
        .join(GeneratedDocument, GeneratedParagraph.document_id == GeneratedDocument.id)
        .where(GeneratedParagraph.id == paragraph_id, GeneratedDocument.session_id == session.id)
    )
    paragraph = (await db.execute(stmt)).scalar_one_or_none()
    if paragraph is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="paragraph_not_found")
    return paragraph


@router.post("/{session_id}/generate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def generate_document(
    payload: GenerateRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    try:
        next_status = orchestrator.require_simple_transition("generate", session.status)
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    # 문서 생성은 카테고리마다 LLM을 순차로 부르는, 이 서비스에서 가장 긴 LLM
    # 경로다. 여기만 LLMUnavailableError를 잡지 않아서 Ollama 장애가 503이 아니라
    # 500으로 나갔고, 그러면 프론트의 llm_unavailable → "AI 서버가 수리 중이예요."
    # 매핑을 타지 못해 사용자에게 정체불명의 오류로 보였다.
    try:
        document = await document_generator.generate_full_document(
            session.id, payload.tone, db, llm, embedding_provider=embedding_provider
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc
    session.status = next_status
    await db.commit()

    result = await _document_read(document, db, fact_citations)
    result.generation_stats = _gpu_stats(llm)
    return result


@router.get("/{session_id}/document", response_model=DocumentRead)
async def get_document(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    return await _document_read(document, db, fact_citations)


@router.post("/{session_id}/document/regenerate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def regenerate_document(
    payload: GenerateRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    try:
        orchestrator.require_status("regenerate", session.status, "RESULT_REVIEW")
    except orchestrator.StateMachineViolation as exc:
        raise _violation_to_409(exc) from exc

    latest = await _get_latest_document(session.id, db)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    try:
        document = await document_generator.generate_full_document(
            session.id, payload.tone, db, llm, version=latest.version + 1, embedding_provider=embedding_provider
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="llm_unavailable") from exc
    result = await _document_read(document, db, fact_citations)
    result.generation_stats = _gpu_stats(llm)
    return result


@router.patch("/{session_id}/document/sentences/{sentence_id}", response_model=SentenceRead)
async def update_sentence(
    sentence_id: uuid.UUID,
    payload: SentenceUpdate,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> SentenceRead:
    sentence = await _get_owned_sentence(session, sentence_id, db)

    # 재검증 불필요 — 사용자가 직접 쓴 문장은 그 자체로 이미 "확인됨" 상태다
    # (04_document_generation.md 2절). evidence_fact_ids는 그대로 유지한다.
    #
    # 다만 그 True를 "임베딩 정합성 검사를 통과했다"와 같은 배지로 보여주면
    # 거짓말이 된다 — 예전에는 두 경우가 같은 값으로 뭉개져서, 사용자가 근거와
    # 무관한 문장으로 고쳐 써도 화면에는 검증 통과 표시가 그대로 남았다.
    # edited_by_user로 출처를 구분하고, 참고용 점수는 무효화한다(이 문장에 대해
    # 계산된 적 없는 값이므로 이전 점수를 남겨두면 오해를 부른다).
    sentence.text = payload.text
    sentence.consistency_check_passed = True
    sentence.edited_by_user = True
    sentence.consistency_score = None
    await db.commit()
    await db.refresh(sentence)

    return await _sentence_read(sentence, db, fact_citations)


@router.patch("/{session_id}/document/paragraphs/{paragraph_id}", response_model=ParagraphRead)
async def update_paragraph(
    paragraph_id: uuid.UUID,
    payload: ParagraphUpdate,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> ParagraphRead:
    paragraph = await _get_owned_paragraph(session, paragraph_id, db)
    if payload.topic is not None:
        paragraph.topic = payload.topic
    if payload.user_confirmed is not None:
        paragraph.user_confirmed = payload.user_confirmed
    await db.commit()
    await db.refresh(paragraph)
    return await _paragraph_read(paragraph, db, fact_citations)


@router.post("/{session_id}/document/paragraphs/{paragraph_id}/merge-next", response_model=ParagraphRead)
async def merge_paragraph_with_next(
    paragraph_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> ParagraphRead:
    """관련성 확인 단계의 핵심 조작: 인접한 두 문단이 같은 이야기라고 판단되면
    합친다. 임의의 두 문단을 고르는 UI 대신 "다음 문단과 합치기"로 단순화했다
    — 문단은 이미 순서가 있으므로 인접 병합만으로 대부분의 재구성이 된다.
    """
    paragraph = await _get_owned_paragraph(session, paragraph_id, db)
    next_paragraph = (
        await db.execute(
            select(GeneratedParagraph)
            .where(
                GeneratedParagraph.document_id == paragraph.document_id,
                GeneratedParagraph.order_index > paragraph.order_index,
            )
            .order_by(GeneratedParagraph.order_index)
        )
    ).scalars().first()
    if next_paragraph is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no_next_paragraph")

    moved_sentences = (
        await db.execute(
            select(GeneratedSentence).where(GeneratedSentence.paragraph_id == next_paragraph.id)
        )
    ).scalars().all()
    for sentence in moved_sentences:
        sentence.paragraph_id = paragraph.id
    # Must flush the reassignment before deleting next_paragraph — the FK's
    # ON DELETE CASCADE fires against whatever paragraph_id is in the DB at
    # delete time, and without this flush the moved sentences can still
    # point at next_paragraph there, so the cascade deletes them too instead
    # of leaving them re-homed on `paragraph`.
    await db.flush()
    await db.delete(next_paragraph)
    await db.commit()
    await db.refresh(paragraph)
    return await _paragraph_read(paragraph, db, fact_citations)


@router.delete("/{session_id}/document/paragraphs/{paragraph_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paragraph(
    paragraph_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
):
    # No `-> None` return annotation here — see the comment on
    # sessions.delete_session for why that trips FastAPI's 204-response-body
    # assertion under `from __future__ import annotations`.
    #
    # Removes the paragraph's sentences along with it, rather than re-homing
    # them on a neighbor the way merge-next does — this is "delete this whole
    # block", not "combine it with another one". The underlying confirmed_facts
    # those sentences cited are untouched, so nothing about the
    # interview/honesty-guardrail data is lost.
    #
    # Sentences are deleted explicitly (not left to generated_sentences.paragraph_id's
    # ON DELETE CASCADE) — GeneratedParagraph.sentences has no ORM-level delete
    # cascade, and without one, SQLAlchemy's unit-of-work de-associates a
    # deleted parent's loaded children by nulling their FK instead of deleting
    # them, pre-empting the DB constraint entirely. Confirmed by a failing test:
    # deleting a paragraph this way left its sentence behind as an "orphaned
    # sentence" (paragraph_id NULL) rather than removing it.
    paragraph = await _get_owned_paragraph(session, paragraph_id, db)
    sentences = (
        await db.execute(select(GeneratedSentence).where(GeneratedSentence.paragraph_id == paragraph.id))
    ).scalars().all()
    for sentence in sentences:
        await db.delete(sentence)
    await db.delete(paragraph)
    await db.commit()


@router.post("/{session_id}/document/sentences/{sentence_id}/move", response_model=SentenceRead)
async def move_sentence(
    sentence_id: uuid.UUID,
    payload: MoveSentenceRequest,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> SentenceRead:
    """관련성 확인의 또 다른 조작: 문장 하나가 잘못된 문단에 묶였다고 판단되면
    이웃 문단으로 옮긴다. 문단을 하나씩 비우면서 옮기면 사실상 분리(split)도
    이 프리미티브로 구성된다.
    """
    sentence = await _get_owned_sentence(session, sentence_id, db)
    if sentence.paragraph_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="sentence_has_no_paragraph")
    current_paragraph = await db.get(GeneratedParagraph, sentence.paragraph_id)

    if payload.direction == "next":
        comparator = GeneratedParagraph.order_index > current_paragraph.order_index
        order_by = GeneratedParagraph.order_index.asc()
    else:
        comparator = GeneratedParagraph.order_index < current_paragraph.order_index
        order_by = GeneratedParagraph.order_index.desc()

    target_paragraph = (
        await db.execute(
            select(GeneratedParagraph)
            .where(GeneratedParagraph.document_id == current_paragraph.document_id, comparator)
            .order_by(order_by)
        )
    ).scalars().first()
    if target_paragraph is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"no_{payload.direction}_paragraph")

    sentence.paragraph_id = target_paragraph.id
    await db.commit()
    await db.refresh(sentence)
    return await _sentence_read(sentence, db, fact_citations)


@router.post("/{session_id}/document/sentences/{sentence_id}/regenerate", response_model=SentenceRead)
async def regenerate_sentence(
    sentence_id: uuid.UUID,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    fact_citations=Depends(get_fact_citations),
) -> SentenceRead:
    sentence = await _get_owned_sentence(session, sentence_id, db)
    document = await db.get(GeneratedDocument, sentence.document_id)

    try:
        sentence = await document_generator.regenerate_sentence(
            sentence, document.tone, db, llm, embedding_provider=embedding_provider
        )
    except document_generator.NoEvidenceToRegenerateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return await _sentence_read(sentence, db, fact_citations)


@router.get("/{session_id}/documents", response_model=list[DocumentVersionRead])
async def list_document_versions(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> list[GeneratedDocument]:
    """이 세션에서 생성된 문서 버전 목록.

    regenerate는 예전 버전을 지우지 않고 version+1로 새로 쌓아왔는데(9-5절),
    정작 최신 1건 말고는 꺼내볼 방법이 없어서 사실상 쌓기만 하는 상태였다.
    톤을 바꿔 재생성해본 뒤 "아까 게 나았다"로 돌아가려면 이 목록이 있어야 한다.
    """
    stmt = (
        select(GeneratedDocument)
        .where(GeneratedDocument.session_id == session.id)
        .order_by(GeneratedDocument.version.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _unverified_sentences(document: GeneratedDocument, db: AsyncSession) -> list[GeneratedSentence]:
    stmt = (
        select(GeneratedSentence)
        .where(
            GeneratedSentence.document_id == document.id,
            GeneratedSentence.consistency_check_passed.is_(False),
        )
        .order_by(GeneratedSentence.order_index)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("/{session_id}/document/finalize", response_model=DocumentRead)
async def finalize_document(
    payload: FinalizeRequest = FinalizeRequest(),
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> DocumentRead:
    """문서를 FINAL로 확정한다.

    정합성 검사에 걸린 문장이 남아 있으면 기본적으로 막는다(409). 예전에는
    검사 결과가 화면에 노란 배지로 표시될 뿐 확정도 export도 그대로 통과해서,
    가드레일이 사실상 아무것도 집행하지 않았다 — "근거와 맞지 않는 문장"이
    그대로 이력서에 복사돼 나갈 수 있었다.

    사용자가 검토한 뒤에도 그대로 두고 싶다면 acknowledge_unverified=true로
    다시 호출한다. 판단 자체는 사용자 몫이지만, 모르고 지나칠 수는 없게 한다.
    """
    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")

    if not payload.acknowledge_unverified:
        unverified = await _unverified_sentences(document, db)
        if unverified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "unverified_sentences",
                    "sentences": [
                        UnverifiedSentenceRead(
                            id=s.id,
                            order_index=s.order_index,
                            text=s.text,
                            consistency_score=s.consistency_score,
                        ).model_dump(mode="json")
                        for s in unverified
                    ],
                },
            )

    document.status = "FINAL"
    await db.commit()
    await db.refresh(document)

    return await _document_read(document, db, fact_citations)


@router.post("/{session_id}/document/share", response_model=ShareLinkRead)
async def create_share_link(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
) -> ShareLinkRead:
    """공유 링크를 발급(이미 있으면 그대로 재사용)한다. FINAL 문서만 공유
    가능 — 아직 손보는 중인 초안을 밖으로 내보낼 이유가 없다."""
    document = await _get_latest_document(session.id, db)
    if document is None or document.status != "FINAL":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="document_not_finalized")
    if not document.share_slug:
        document.share_slug = secrets.token_urlsafe(9)[:12]
        await db.commit()
        await db.refresh(document)
    return ShareLinkRead(share_slug=document.share_slug)


@router.delete("/{session_id}/document/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
):
    # No `-> None` annotation — see sessions.delete_session's comment on why
    # that trips FastAPI's 204-response-body assertion under
    # `from __future__ import annotations`.
    document = await _get_latest_document(session.id, db)
    if document is not None and document.share_slug is not None:
        document.share_slug = None
        await db.commit()


_EXPORT_FORMATS = ("txt", "md")


async def _citation_lines(
    sentences: list[GeneratedSentence], db: AsyncSession, fact_citations
) -> list[str]:
    """근거 부록 — 문서에 인용된 기록물의 출처를 URL/게시일과 함께 나열한다.

    export가 문장 텍스트만 뱉던 동안에는, 인터뷰 내내 모은 출처가 복사-붙여넣기
    한 번에 전부 증발했다. 근거가 결과물까지 살아남지 않으면 근거를 모은 의미가
    없다. 본문에는 손대지 않고 문서 끝에만 덧붙인다 — 경력기술서 본문에 각주
    기호가 섞여 들어가면 그대로 갖다 쓸 수 없기 때문이다.
    """
    fact_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for s in sentences:
        for fid_str in s.evidence_fact_ids:
            fid = uuid.UUID(fid_str)
            if fid not in seen:
                seen.add(fid)
                fact_ids.append(fid)

    citations = await fact_citations(fact_ids, db)
    lines: list[str] = []
    for fid in fact_ids:
        citation = citations.get(fid)
        if citation is None or not citation.source_url:
            continue
        fact = await db.get(ConfirmedFact, fid)
        content = fact.content if fact is not None else ""
        dated = f" ({citation.published_at})" if citation.published_at else ""
        lines.append(f"- {content}{dated} — {citation.source_url}")
    return lines


@router.get("/{session_id}/export")
async def export_document(
    format: str = "txt",
    citations: bool = False,
    session: SessionModel = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    fact_citations=Depends(get_fact_citations),
) -> PlainTextResponse:
    if format not in _EXPORT_FORMATS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_format")

    document = await _get_latest_document(session.id, db)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    if document.status != "FINAL":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="document_not_finalized")

    para_stmt = (
        select(GeneratedParagraph)
        .where(GeneratedParagraph.document_id == document.id)
        .order_by(GeneratedParagraph.order_index)
    )
    paragraphs = (await db.execute(para_stmt)).scalars().all()

    sent_stmt = (
        select(GeneratedSentence)
        .where(GeneratedSentence.document_id == document.id)
        .order_by(GeneratedSentence.order_index)
    )
    sentences = (await db.execute(sent_stmt)).scalars().all()

    # Sentences within a paragraph read as one flowing block (space-joined,
    # not one per line); paragraphs are separated by a blank line. The topic
    # label itself is a review-screen aid, not resume prose, so it's never
    # included in the exported text.
    sentences_by_paragraph: dict = {p.id: [] for p in paragraphs}
    blocks: list[tuple[int, str]] = []
    for s in sentences:
        if s.paragraph_id is not None and s.paragraph_id in sentences_by_paragraph:
            sentences_by_paragraph[s.paragraph_id].append(s.text)
        else:
            blocks.append((s.order_index, s.text))
    for p in paragraphs:
        if sentences_by_paragraph[p.id]:
            blocks.append((p.order_index, " ".join(sentences_by_paragraph[p.id])))
    blocks.sort(key=lambda b: b[0])

    text = "\n\n".join(block_text for _, block_text in blocks)

    if citations:
        lines = await _citation_lines(list(sentences), db, fact_citations)
        if lines:
            heading = "## 근거 자료" if format == "md" else "[근거 자료]"
            text = f"{text}\n\n{heading}\n" + "\n".join(lines)

    media_type = "text/markdown; charset=utf-8" if format == "md" else "text/plain; charset=utf-8"
    return PlainTextResponse(content=text, media_type=media_type)
