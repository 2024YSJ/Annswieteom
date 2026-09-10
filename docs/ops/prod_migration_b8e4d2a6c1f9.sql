-- 프로덕션 Supabase SQL Editor에서 실행할 마이그레이션
-- 생성: alembic upgrade f3b6d0c8a114:b8e4d2a6c1f9 --sql  (2026-09-11)
-- 대상 리비전: f3b6d0c8a114 -> b8e4d2a6c1f9
--   (user_attributes, user_consents, feed_items.eligibility — 대화 기반 프로필 + 티어 매칭)
--
-- ⚠️ 실행 전에 반드시 확인:
--     SELECT version_num FROM alembic_version;
--   결과가 'f3b6d0c8a114'가 아니면 이 스크립트를 실행하지 마세요.
--   아래 UPDATE 문이 WHERE에 걸리지 않아 조용히 no-op이 되는데,
--   CREATE TABLE은 그대로 실행됩니다 — 테이블은 생겼는데 alembic은
--   모르는 상태가 되고, 이후 `alembic upgrade head`가 중복 생성으로 실패합니다.
--
-- ⚠️ 맨 아래 UPDATE alembic_version 문을 빼고 붙여넣지 마세요. 같은 이유입니다.
--
-- 전체가 BEGIN/COMMIT 한 트랜잭션이라 중간에 실패하면 전부 롤백됩니다.
-- 새 컬럼 feed_items.eligibility는 NULL로 추가되고, 다음 피드 수집(6시간 TTL,
-- 또는 메인 화면 첫 방문 시 백그라운드)에서 온통청년 정책에 채워집니다.
-- 그 전까지 맞춤 정책은 모든 정책을 "조건 정보 없음"(티어 none)으로 봅니다.

BEGIN;

-- Running upgrade f3b6d0c8a114 -> b8e4d2a6c1f9

CREATE TABLE user_attributes (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    key TEXT NOT NULL,
    value JSON NOT NULL,
    value_norm TEXT NOT NULL,
    status TEXT DEFAULT 'inferred' NOT NULL,
    sensitive BOOLEAN DEFAULT false NOT NULL,
    source_kind TEXT NOT NULL,
    source_answer_id UUID,
    evidence_text TEXT,
    invalidated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_user_attributes_key CHECK (key IN ('birth_year', 'residence_region', 'desired_region', 'education_level', 'major_field', 'employment_status', 'desired_job', 'desired_employment_type', 'skills', 'certificates', 'interests', 'annual_income', 'special_groups', 'marital_status')),
    CONSTRAINT ck_user_attributes_status CHECK (status IN ('inferred', 'confirmed', 'user_edited', 'rejected')),
    CONSTRAINT ck_user_attributes_source_kind CHECK (source_kind IN ('interview_answer', 'job_search', 'wish_text', 'profile_form')),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(source_answer_id) REFERENCES interview_answers (id) ON DELETE SET NULL
);

CREATE INDEX ix_user_attributes_user_key ON user_attributes (user_id, key);

CREATE TABLE user_consents (
    user_id UUID NOT NULL,
    consent_type TEXT NOT NULL,
    granted BOOLEAN DEFAULT false NOT NULL,
    granted_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    sensitive_mentioned_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id, consent_type),
    CONSTRAINT ck_user_consents_type CHECK (consent_type IN ('sensitive_profiling')),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

ALTER TABLE feed_items ADD COLUMN eligibility JSON;

UPDATE alembic_version SET version_num='b8e4d2a6c1f9' WHERE alembic_version.version_num = 'f3b6d0c8a114';

COMMIT;
