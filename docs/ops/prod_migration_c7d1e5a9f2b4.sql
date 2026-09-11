-- 프로덕션 Supabase SQL Editor에서 실행할 마이그레이션
-- 생성: alembic upgrade b8e4d2a6c1f9:c7d1e5a9f2b4 --sql  (2026-09-11)
-- 대상 리비전: b8e4d2a6c1f9 -> c7d1e5a9f2b4
--   (activity_categories.draft_turns — 카테고리 단위 사실 확인)
--
-- ⚠️ 실행 전에 반드시 확인:
--     SELECT version_num FROM alembic_version;
--   결과가 'b8e4d2a6c1f9'가 아니면 이 스크립트를 실행하지 마세요.
--   아래 UPDATE 문이 WHERE에 걸리지 않아 조용히 no-op이 되는데,
--   ALTER TABLE은 그대로 실행됩니다 — 컬럼은 생겼는데 alembic은
--   모르는 상태가 되고, 이후 `alembic upgrade head`가 중복 추가로 실패합니다.
--
-- ⚠️ 맨 아래 UPDATE alembic_version 문을 빼고 붙여넣지 마세요. 같은 이유입니다.
--
-- ⚠️ 배포 순서: 이 SQL → 백엔드 배포 → 프론트 배포.
--   새 백엔드는 세션 조회(GET /sessions/{id})에서 이 컬럼을 읽으므로, 컬럼 없이
--   먼저 뜨면 세션 화면 전체가 500이 됩니다. 컬럼만 추가하는 변경이라 지금 운영 중인
--   코드에는 영향이 없습니다(먼저 실행해도 안전).

BEGIN;

-- Running upgrade b8e4d2a6c1f9 -> c7d1e5a9f2b4

ALTER TABLE activity_categories ADD COLUMN draft_turns JSON;

UPDATE alembic_version SET version_num='c7d1e5a9f2b4' WHERE alembic_version.version_num = 'b8e4d2a6c1f9';

COMMIT;
