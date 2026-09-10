from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"

    # Comma-separated list of allowed frontend origins for CORS. Local dev
    # only needs localhost:3000; deployed environments (Render) must add
    # the Vercel domains via this env var — see app/main.py.
    cors_allow_origins: str = "http://localhost:3000"

    database_url: str
    jwt_secret: str
    jwt_access_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 14

    local_llm_base_url: str = "http://localhost:11434"
    # Was "exaone3.5:7.8b", which doesn't match any tag actually pulled on the
    # real server (only "exaone3.5:latest" exists there) — silently 404s if
    # LOCAL_LLM_MODEL_NAME is ever unset, instead of falling back cleanly.
    # Matches .env.example's documented default.
    local_llm_model_name: str = "qwen2.5:14b"
    # 2026-09-09 Gemini 폴백을 제거했다. 추론/임베딩 경로가 로컬 Ollama 하나뿐이라
    # 이 서버가 닿지 않으면 AI 기능은 503(llm_unavailable)으로 끝난다 — 대체 경로는
    # 없고, 화면에는 "AI 서버가 수리 중이예요."가 뜬다.

    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_storage_bucket: str = "records"

    # 워크넷(고용24) Open API — 무료, 조회 전용. https://www.work24.go.kr 회원가입
    # 후 카테고리별로 각각 신청하면 담당자 심사를 거쳐 발급된다(신청 즉시
    # 발급이 아니고, 카테고리마다 별도 키 — 2026-09-08 devlog 15/16 참고).
    # "채용정보"(구인정보 검색) 자체는 개인회원 계정을 차단해서(devlog 15) 못
    # 쓰지만, 같은 신청으로 딸려오는 형제 API 3개(채용행사/공채속보/
    # 공채기업정보)는 정상 작동해 job_info_client.py가 이 키로 쓴다.
    worknet_job_posting_api_key: str = ""
    worknet_employer_training_api_key: str = ""  # 사업주훈련 훈련과정
    worknet_consortium_training_api_key: str = ""  # 국가인적자원개발 컨소시엄 훈련과정
    worknet_work_study_training_api_key: str = ""  # 일학습병행 훈련과정
    worknet_tomorrow_learning_card_api_key: str = ""  # 국민내일배움카드 훈련과정
    worknet_job_seeker_program_api_key: str = ""  # 구직자취업역량 강화프로그램
    worknet_promising_sme_api_key: str = ""  # 강소기업

    # 온통청년(youthcenter.go.kr) 청년정책 통합 Open API - 무료, 조회 전용.
    # 회원가입 후 [마이페이지 - OPEN API]에서 신청하면 워크넷과 마찬가지로
    # 담당자 심사를 거쳐 발급된다. 비어 있으면 이 소스는 오류가 아니라 그냥
    # 수집 대상에서 빠지고, 지원 정책 피드는 워크넷의 직업훈련과정/구직자
    # 취업역량강화프로그램으로 채워진다(services/feed/sources/__init__.py).
    youthcenter_api_key: str = ""

    # 피드 캐시가 이 시간을 넘기면 다음 조회 요청이 백그라운드 갱신을 예약한다
    # (응답 자체는 캐시에서 즉시 나간다 - stale-while-revalidate). 기본 6시간은
    # 공고/정책이 잘해야 하루 단위로 바뀌는 데 비해 충분히 촘촘하면서,
    # 심사받아 얻은 API 쿼터를 아끼는 값이다.
    feed_refresh_ttl_seconds: int = 21600

    # 12-4절: 생성된 문장과 인용된 confirmed_facts 간 코사인 유사도 최소값.
    # 0.45~0.65 범위에서 실제 생성 샘플로 튜닝 — app/services/consistency_check.py 참고.
    consistency_threshold: float = 0.55

    class Config:
        env_file = ".env"


settings = Settings()
