-- 프로덕션 Supabase SQL Editor에서 실행할 마이그레이션
-- 생성: alembic upgrade 735683a2d64a:head --sql  (2026-09-09)
-- 대상 리비전: 735683a2d64a -> d8c1b4a70f22 -> e7a1c93d5b20
--
-- ⚠️ 실행 전에 반드시 확인:
--     SELECT version_num FROM alembic_version;
--   결과가 '735683a2d64a'가 아니면 이 스크립트를 실행하지 마세요.
--   아래 UPDATE 문이 WHERE에 걸리지 않아 조용히 no-op이 되는데,
--   CREATE TABLE은 그대로 실행됩니다 — 테이블은 생겼는데 alembic은
--   모르는 상태가 되고, 이후 `alembic upgrade head`가 중복 생성으로 실패합니다.
--
-- ⚠️ 맨 아래 두 UPDATE alembic_version 문을 빼고 붙여넣지 마세요. 같은 이유입니다.
--
-- 전체가 BEGIN/COMMIT 한 트랜잭션이라 중간에 실패하면 전부 롤백됩니다.
-- pgvector 확장은 record_chunks가 이미 쓰고 있어 별도 조치가 필요 없습니다
-- (확인: SELECT extversion FROM pg_extension WHERE extname='vector';).

BEGIN;

-- Running upgrade 735683a2d64a -> d8c1b4a70f22

CREATE TABLE interview_answers (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    session_id UUID, 
    category_label TEXT NOT NULL, 
    category_type TEXT NOT NULL, 
    question_text TEXT NOT NULL, 
    question_source TEXT NOT NULL, 
    answer_text TEXT NOT NULL, 
    confirmed_facts JSON DEFAULT '[]' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE SET NULL
);

CREATE INDEX ix_interview_answers_user_id ON interview_answers (user_id);

ALTER TABLE activity_categories ADD COLUMN period_start DATE;

ALTER TABLE activity_categories ADD COLUMN period_end DATE;

ALTER TABLE activity_categories ADD COLUMN period_source VARCHAR(20);

ALTER TABLE activity_categories ADD CONSTRAINT ck_activity_categories_period_source CHECK (period_source IN ('ai_inferred', 'user_set'));

ALTER TABLE generated_sentences ADD COLUMN consistency_score FLOAT;

ALTER TABLE generated_sentences ADD COLUMN edited_by_user BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE generated_sentences ALTER COLUMN edited_by_user DROP DEFAULT;

UPDATE alembic_version SET version_num='d8c1b4a70f22' WHERE alembic_version.version_num = '735683a2d64a';

-- Running upgrade d8c1b4a70f22 -> e7a1c93d5b20

CREATE TABLE feed_items (
    id UUID NOT NULL, 
    source TEXT NOT NULL, 
    category TEXT NOT NULL, 
    feed_kind TEXT NOT NULL, 
    dedup_key TEXT NOT NULL, 
    title TEXT NOT NULL, 
    subtitle TEXT DEFAULT '' NOT NULL, 
    meta_lines JSON DEFAULT '[]' NOT NULL, 
    detail_url TEXT, 
    source_published_at DATE, 
    embed_text TEXT DEFAULT '' NOT NULL, 
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_feed_items_identity UNIQUE (source, category, dedup_key), 
    CONSTRAINT ck_feed_items_source CHECK (source IN ('worknet', 'youthcenter')), 
    CONSTRAINT ck_feed_items_feed_kind CHECK (feed_kind IN ('job', 'policy')), 
    CONSTRAINT ck_feed_items_category CHECK (category IN ('job_fair', 'public_recruitment', 'public_recruitment_company', 'promising_sme', 'training_course', 'job_seeker_program', 'youth_policy'))
);

CREATE INDEX ix_feed_items_active_recent ON feed_items (is_active, feed_kind, first_seen_at);

CREATE TABLE feed_item_embeddings (
    feed_item_id UUID NOT NULL, 
    embedding VECTOR(1024), 
    embedding_model TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (feed_item_id), 
    FOREIGN KEY(feed_item_id) REFERENCES feed_items (id) ON DELETE CASCADE
);

CREATE TABLE user_profile_embeddings (
    user_id UUID NOT NULL, 
    embedding VECTOR(1024), 
    embedding_model TEXT, 
    source_fingerprint TEXT, 
    source_answer_count INTEGER DEFAULT '0' NOT NULL, 
    source_latest_answer_at TIMESTAMP WITH TIME ZONE, 
    profile_text TEXT, 
    computed_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (user_id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE feed_refresh_states (
    id UUID NOT NULL, 
    source_key TEXT NOT NULL, 
    last_started_at TIMESTAMP WITH TIME ZONE, 
    last_succeeded_at TIMESTAMP WITH TIME ZONE, 
    last_failed_at TIMESTAMP WITH TIME ZONE, 
    last_error TEXT, 
    item_count INTEGER DEFAULT '0' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_feed_refresh_states_source_key UNIQUE (source_key)
);

UPDATE alembic_version SET version_num='e7a1c93d5b20' WHERE alembic_version.version_num = 'd8c1b4a70f22';

COMMIT;

