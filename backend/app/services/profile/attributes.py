"""대화에서 사람 단위 속성을 뽑아 저장하고, 매칭·대화용으로 읽는다.

흐름(Mem0의 추출 → 조정 두 단계를 규칙 기반으로 줄인 것):

1. 추출 — 사용자가 한 말 하나(인터뷰 답변, 구직 검색 질문, 희망사항)를 LLM에
   넘겨 속성 후보를 받는다. **백그라운드에서만** 돈다(요청 경로의 LLM 호출 수를
   늘리지 않는다).
2. 검증 — 후보마다 사용자 원문 인용(evidence)이 실제 원문에 있는지 확인한다.
   없으면 모델이 지어낸 것이므로 버린다. 동의 없는 민감 키도 여기서 버린다
   (프롬프트 지시와 별개로 서버가 최종 차단).
3. 조정 — 같은 값이면 무시, 사용자가 확인·수정한 값은 절대 덮어쓰지 않음, 추정
   값끼리는 새 값이 옛 값을 무효화(이력 보존), 사용자가 지운 값은 되살리지 않음.

**정직성 가드레일:** 여기서 저장한 속성은 추천·대화 보조에만 쓴다. 생성 문서는
여전히 confirmed_facts만 인용하고, 이 값은 document_generator로 흐르지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.user_attribute import (
    ATTRIBUTE_KEYS,
    MULTI_VALUED_KEYS,
    NON_SENSITIVE_KEYS,
    SENSITIVE_KEYS,
    UserAttribute,
)
from app.models.user_consent import UserConsent
from app.services.feed.matching import MatchProfile
from app.services.job_pipeline.regions import region_code_for
from app.services.llm.base import AttributeCandidate
from app.services.profile.vocabulary import CHOICES, KEY_LABELS, label_to_code

logger = logging.getLogger(__name__)

SENSITIVE_CONSENT = "sensitive_profiling"

#: 이보다 짧은 발화는 추출하지 않는다 — "네", "없어요" 같은 답에 32b 호출을
#: 쓰지 않기 위해서다. "수원 살아요"(6자)처럼 짧아도 정보가 있는 답이 있어 낮게 둔다.
MIN_EXTRACT_CHARS = 6

#: 사용자별 추출 직렬화. 한 사용자의 연속 답변이 동시에 조정 단계를 돌면 같은
#: 키에 두 행이 활성으로 남을 수 있다. 어차피 로컬 Ollama가 직렬 처리하므로
#: 줄 세워도 잃는 게 없다(ingest._EMBED_LOCK과 같은 판단). 프로세스 단위 락이다.
_USER_LOCKS: dict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

_STATUS_RANK = {"user_edited": 0, "confirmed": 1, "inferred": 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _norm_text(label: str) -> str:
    return _squash(label).lower()


def normalize(key: str, label: str, today: date | None = None) -> tuple[dict, str] | None:
    """라벨 → (저장할 value, 비교용 value_norm). 쓸 수 없는 값이면 None."""
    label = " ".join(str(label or "").split())[:60]
    if not label or key not in ATTRIBUTE_KEYS:
        return None
    today = today or date.today()

    if key == "birth_year":
        digits = re.findall(r"\d+", label)
        if not digits:
            return None
        n = int(digits[0])
        if 1900 <= n <= today.year:
            year = n
        elif 10 <= n <= 80:
            # "26살". 세는 나이인지 만 나이인지 모르므로 출생연도가 1년 어긋날 수
            # 있다 — 매칭이 경계 ±1년을 미확인으로 두는 이유다(matching.AGE_MARGIN).
            year = today.year - n
        else:
            return None
        if not (today.year - 80 <= year <= today.year - 10):
            return None
        return {"label": f"{year}년생", "year": year}, str(year)

    if key == "annual_income":
        digits = re.findall(r"\d+", label.replace(",", ""))
        if not digits:
            return None
        amount = int(digits[0])
        if "월" in label:
            amount *= 12
        if not 0 < amount <= 100_000:
            return None
        return {"label": f"연 {amount:,}만원", "amount": amount}, str(amount)

    if key in ("residence_region", "desired_region"):
        if label not in CHOICES[key]:
            return None
        code = region_code_for(label)
        # 거주지는 매칭의 하드 조건이라 코드로 못 푸는 값("수도권")은 저장하지 않는다.
        if key == "residence_region" and code is None:
            return None
        return {"label": label, "code": code}, code or _norm_text(label)

    if key in CHOICES:
        if label not in CHOICES[key]:
            return None
        code = label_to_code(key, label)
        return {"label": label, "code": code}, code or label

    return {"label": label[:40]}, _norm_text(label)


#: 인용이 원문과 이만큼 이상 겹치면(가장 긴 공통 구간 기준) 옮겨 적은 것으로 본다.
#: 정확한 부분문자열만 받았더니 실모델(qwen2.5:3b, 2026-09-11)이 "수원에 살고 있고"를
#: "수원에 살고 있어요"로 어미만 바꿔 옮겨 멀쩡한 사실이 버려졌다. 반대로 프롬프트
#: 예시를 베낀 인용은 원문과 두세 글자밖에 안 겹쳐 여기서 걸린다.
_MIN_EVIDENCE_OVERLAP = 0.6

_REGION_KEYS = frozenset({"residence_region", "desired_region"})

#: 목록 없이 자유 텍스트로 받는 키. 값 자체가 원문에 그대로 있어야 받는다 — 실모델이
#: "백엔드 개발자"를 "백엔드 개veloper"로 깨뜨려 냈다(qwen2.5:3b, 2026-09-11). 사용자가
#: 쓴 표현만 남기는 보수적인 규칙이라, 모델이 요약한 표현("데이터 분석가")은 버려질 수
#: 있다 — 틀린 걸 저장하는 것보다 비워 두는 편이 낫고, 사용자가 직접 적을 수 있다.
_FREE_TEXT_KEYS = frozenset({"desired_job", "skills", "certificates", "interests"})

#: 동의 없는 사용자가 민감정보를 말했는지 알아채는 결정적 안전망. 모델이 놓쳐도
#: (실측: "한부모 가정이라…"에서 3b가 아무것도 안 냈다) 동의 카드 강조는 켜진다.
#: 값을 저장하는 게 아니라 표시 하나를 켤 뿐이라, 넓게 잡아도 대가가 작다. 다만
#: "월급", "결혼"처럼 과거 일 이야기에 흔한 말은 넣지 않았다.
_SENSITIVE_HINT = re.compile(r"한부모|장애|기초생활|수급자|차상위|연소득|연봉|신혼|기혼|미혼")


def _expand(candidate: AttributeCandidate) -> list[AttributeCandidate]:
    """다중값 자유 텍스트를 쪼갠다 — 모델이 "파이썬, SQL"을 한 값으로 냈다."""
    if candidate.key in MULTI_VALUED_KEYS and candidate.key not in CHOICES:
        parts = [p.strip() for p in re.split(r"[,，·/]", candidate.value_label) if p.strip()]
        if len(parts) > 1:
            return [AttributeCandidate(key=candidate.key, value_label=p, evidence=candidate.evidence) for p in parts]
    return [candidate]


def _is_quoted(evidence: str, source: str) -> bool:
    if len(evidence) < 2:
        return False
    if evidence in source:
        return True
    match = SequenceMatcher(None, source, evidence, autojunk=False).find_longest_match(
        0, len(source), 0, len(evidence)
    )
    return match.size >= max(2, math.ceil(len(evidence) * _MIN_EVIDENCE_OVERLAP))


def validate_candidates(
    candidates: list[AttributeCandidate], source_text: str, allow_sensitive: bool
) -> tuple[list[AttributeCandidate], bool]:
    """(남길 후보, 동의 없이 민감정보가 언급됐는가).

    인용 비교는 공백을 전부 지우고 한다 — 모델이 띄어쓰기를 바꿔 옮기는 건
    흔하고, 그건 지어낸 게 아니다. 어미를 바꾼 정도의 의역도 받는다(_is_quoted).

    지역은 한 단계 더 엄격하다: 지명 자체가 원문에 있어야 한다. 실모델이 "경기
    남부에서 일하고 싶어요"에 프롬프트 예시의 "수원"을 그대로 붙여 냈다 — 거주지는
    매칭의 하드 조건이라, 틀리면 맞는 정책이 통째로 빠진다.
    """
    source = _squash(source_text)
    kept: list[AttributeCandidate] = []
    mentioned = False
    for candidate in (c for raw in candidates for c in _expand(raw)):
        if candidate.key not in ATTRIBUTE_KEYS:
            continue
        if not _is_quoted(_squash(candidate.evidence), source):
            continue
        if candidate.key in _REGION_KEYS | _FREE_TEXT_KEYS and _squash(candidate.value_label) not in source:
            continue
        if candidate.key in SENSITIVE_KEYS and not allow_sensitive:
            mentioned = True
            continue
        kept.append(candidate)
    if not allow_sensitive and not mentioned and _SENSITIVE_HINT.search(source_text or ""):
        mentioned = True
    return kept, mentioned


async def reconcile(
    db: AsyncSession,
    user_id: uuid.UUID,
    candidates: list[AttributeCandidate],
    *,
    source_kind: str,
    source_answer_id: uuid.UUID | None = None,
    today: date | None = None,
) -> int:
    """검증된 후보를 저장한다. 새로 넣은 행 수를 돌려준다. 커밋은 호출자가 한다."""
    added = 0
    for candidate in candidates:
        normalized = normalize(candidate.key, candidate.value_label, today)
        if normalized is None:
            continue
        value, norm = normalized
        rows = (
            await db.execute(
                select(UserAttribute).where(UserAttribute.user_id == user_id, UserAttribute.key == candidate.key)
            )
        ).scalars().all()
        # 사용자가 지운 값은 다음 대화에서 또 나와도 되살리지 않는다.
        if any(r.status == "rejected" and r.value_norm == norm for r in rows):
            continue
        active = [r for r in rows if r.invalidated_at is None and r.status != "rejected"]
        if any(r.value_norm == norm for r in active):
            continue
        if candidate.key not in MULTI_VALUED_KEYS:
            # 사용자가 확인했거나 직접 고친 값은 대화 추정으로 덮어쓰지 않는다.
            if any(r.status in ("confirmed", "user_edited") for r in active):
                continue
            now = _now()
            for r in active:
                r.invalidated_at = now
        db.add(
            UserAttribute(
                user_id=user_id,
                key=candidate.key,
                value=value,
                value_norm=norm,
                status="inferred",
                sensitive=candidate.key in SENSITIVE_KEYS,
                source_kind=source_kind,
                source_answer_id=source_answer_id,
                evidence_text=candidate.evidence[:300],
            )
        )
        # 같은 응답에 같은 키 후보가 둘 오면 두 번째가 첫 번째를 봐야 한다.
        await db.flush()
        added += 1
    return added


async def active_attributes(db: AsyncSession, user_id: uuid.UUID) -> list[UserAttribute]:
    return list(
        (
            await db.execute(
                select(UserAttribute)
                .where(
                    UserAttribute.user_id == user_id,
                    UserAttribute.invalidated_at.is_(None),
                    UserAttribute.status != "rejected",
                )
                .order_by(UserAttribute.key, UserAttribute.created_at, UserAttribute.id)
            )
        ).scalars().all()
    )


def _aware(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return (value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)).timestamp()


def _best(rows: list[UserAttribute]) -> UserAttribute:
    """단일값 키에 활성 행이 여럿일 때(정상이라면 없다) 사용자 손을 탄 값, 그다음 최신."""
    return min(rows, key=lambda r: (_STATUS_RANK.get(r.status, 9), -_aware(r.created_at)))


async def get_sensitive_consent(db: AsyncSession, user_id: uuid.UUID) -> UserConsent | None:
    return await db.get(UserConsent, (user_id, SENSITIVE_CONSENT))


async def has_sensitive_consent(db: AsyncSession, user_id: uuid.UUID) -> bool:
    row = await get_sensitive_consent(db, user_id)
    return bool(row is not None and row.granted)


async def load_match_profile(db: AsyncSession, user_id: uuid.UUID) -> MatchProfile:
    """매칭 입력. 읽기 실패(마이그레이션 이전 등)는 빈 프로필 — 피드가 500이 되면 안 된다."""
    try:
        rows = await active_attributes(db, user_id)
        consent = await has_sensitive_consent(db, user_id)
    except Exception:
        await db.rollback()
        logger.warning("profile: attributes unreadable; matching without them", exc_info=True)
        return MatchProfile()

    by_key: dict[str, list[UserAttribute]] = defaultdict(list)
    for row in rows:
        if row.sensitive and not consent:
            continue
        by_key[row.key].append(row)

    def one(key: str, field: str):
        found = by_key.get(key)
        return (_best(found).value or {}).get(field) if found else None

    special = frozenset(
        code for row in by_key.get("special_groups", []) if (code := (row.value or {}).get("code"))
    )
    desired: set[str] = set()
    for row in by_key.get("desired_region", []):
        value = row.value or {}
        if value.get("code"):
            desired.add(value["code"])
        elif value.get("label") == "수도권":
            # 광역이 셋이라 코드 하나로 저장하지 못한 값(normalize 참고) — 정렬에서는 펼친다.
            desired.update({"11", "41", "28"})
    return MatchProfile(
        desired_region_codes=frozenset(desired),
        birth_year=one("birth_year", "year"),
        residence_code=one("residence_region", "code"),
        education_code=one("education_level", "code"),
        major_code=one("major_field", "code"),
        employment_code=one("employment_status", "code"),
        special_codes=special,
        marital_code=one("marital_status", "code"),
        annual_income=one("annual_income", "amount"),
    )


async def profile_summary_lines(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """대화 프롬프트에 넣을 "이미 아는 정보" 줄. **비민감 키만.**

    인터뷰 요청 도중(사실을 flush한 뒤)에도 불리므로 실패해도 바깥 트랜잭션을
    망치면 안 된다 — Postgres는 실패한 문장 하나로 트랜잭션 전체를 abort시킨다.
    그래서 세이브포인트 안에서 읽는다.
    """
    try:
        async with db.begin_nested():
            rows = await active_attributes(db, user_id)
    except Exception:
        logger.warning("profile: summary unavailable", exc_info=True)
        return []
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.sensitive or row.key not in NON_SENSITIVE_KEYS:
            continue
        label = (row.value or {}).get("label")
        if label and label not in grouped[row.key]:
            grouped[row.key].append(label)
    return [f"{KEY_LABELS[k]}: {', '.join(grouped[k])}" for k in NON_SENSITIVE_KEYS if grouped.get(k)]


async def set_sensitive_consent(db: AsyncSession, user_id: uuid.UUID, granted: bool) -> UserConsent:
    """동의/철회. 철회하면 민감 속성을 **완전히 지운다**(무효화가 아니라 삭제) —
    동의 없이 보관할 근거가 없다. 커밋은 호출자가 한다."""
    row = await get_sensitive_consent(db, user_id)
    if row is None:
        row = UserConsent(user_id=user_id, consent_type=SENSITIVE_CONSENT, granted=False)
        db.add(row)
    now = _now()
    if granted:
        row.granted = True
        row.granted_at = now
        row.revoked_at = None
    else:
        row.granted = False
        row.revoked_at = now
        row.sensitive_mentioned_at = None
        await db.execute(
            delete(UserAttribute).where(UserAttribute.user_id == user_id, UserAttribute.sensitive.is_(True))
        )
    await db.flush()
    return row


async def note_sensitive_mention(db: AsyncSession, user_id: uuid.UUID) -> None:
    """동의 없이 민감정보가 언급됐다는 표시만 남긴다(값은 저장하지 않는다)."""
    row = await get_sensitive_consent(db, user_id)
    if row is None:
        row = UserConsent(user_id=user_id, consent_type=SENSITIVE_CONSENT, granted=False)
        db.add(row)
    if not row.granted:
        row.sensitive_mentioned_at = _now()


async def forget_answer(db: AsyncSession, user_id: uuid.UUID, answer_id: uuid.UUID) -> None:
    """원 답변을 지우면 거기서 추정한 값과 복제된 인용도 지운다.

    사용자가 확인·수정한 값은 이제 사용자 본인의 입력이므로 남기되, 원문
    인용(evidence_text)은 지운다 — 원문을 지웠는데 그 일부가 여기 남으면 안 된다.
    """
    await db.execute(
        delete(UserAttribute).where(
            UserAttribute.user_id == user_id,
            UserAttribute.source_answer_id == answer_id,
            UserAttribute.status == "inferred",
        )
    )
    rows = (
        await db.execute(
            select(UserAttribute).where(
                UserAttribute.user_id == user_id, UserAttribute.source_answer_id == answer_id
            )
        )
    ).scalars().all()
    for row in rows:
        row.evidence_text = None
        row.source_answer_id = None


async def add_user_value(db: AsyncSession, user_id: uuid.UUID, key: str, label: str) -> UserAttribute:
    """프로필 화면에서 직접 입력. 값이 쓸 수 없으면 ValueError. 커밋은 호출자가."""
    normalized = normalize(key, label)
    if normalized is None:
        raise ValueError("invalid_attribute_value")
    value, norm = normalized
    active = [r for r in await active_attributes(db, user_id) if r.key == key]
    for row in active:
        if row.value_norm == norm:
            row.status = "user_edited"
            return row
    if key not in MULTI_VALUED_KEYS:
        now = _now()
        for row in active:
            row.invalidated_at = now
    row = UserAttribute(
        user_id=user_id,
        key=key,
        value=value,
        value_norm=norm,
        status="user_edited",
        sensitive=key in SENSITIVE_KEYS,
        source_kind="profile_form",
    )
    db.add(row)
    await db.flush()
    return row


async def edit_value(db: AsyncSession, row: UserAttribute, label: str) -> UserAttribute:
    normalized = normalize(row.key, label)
    if normalized is None:
        raise ValueError("invalid_attribute_value")
    row.value, row.value_norm = normalized
    row.status = "user_edited"
    await db.flush()
    return row


async def extract_and_store_attributes(
    user_id: uuid.UUID,
    source_kind: str,
    text: str,
    source_answer_id: uuid.UUID | None = None,
) -> None:
    """백그라운드 워커 — 절대 호출자에게 예외를 던지지 않는다.

    BackgroundTasks는 응답을 보낸 뒤에 돌기 때문에 요청 세션은 이미 닫혀 있다.
    자기 세션을 연다(refresh_profile_embedding과 같은 규칙).
    """
    text = (text or "").strip()
    if len(text) < MIN_EXTRACT_CHARS:
        return
    # 순환 import 방지: services.llm은 프롬프트용으로 profile.vocabulary를 import한다.
    from app.services.llm import get_llm_provider

    async with _USER_LOCKS[user_id]:
        try:
            async with AsyncSessionLocal() as db:
                allow_sensitive = await has_sensitive_consent(db, user_id)
                known = await profile_summary_lines(db, user_id)
                candidates = await get_llm_provider().extract_profile_attributes(text, known, allow_sensitive)
                kept, mentioned = validate_candidates(candidates, text, allow_sensitive)
                if mentioned:
                    await note_sensitive_mention(db, user_id)
                await reconcile(
                    db, user_id, kept, source_kind=source_kind, source_answer_id=source_answer_id
                )
                await db.commit()
        except Exception:
            logger.warning("profile: attribute extraction failed for %s", user_id, exc_info=True)


def get_profile_extractor():
    """FastAPI DI 훅. 워커가 자기 세션을 열어서 get_db 오버라이드로는 테스트에서
    못 막는다(get_profile_embedder와 같은 이유)."""
    return extract_and_store_attributes


__all__ = [
    "SENSITIVE_CONSENT",
    "active_attributes",
    "add_user_value",
    "edit_value",
    "extract_and_store_attributes",
    "forget_answer",
    "get_profile_extractor",
    "get_sensitive_consent",
    "has_sensitive_consent",
    "load_match_profile",
    "normalize",
    "note_sensitive_mention",
    "profile_summary_lines",
    "reconcile",
    "set_sensitive_consent",
    "validate_candidates",
]
