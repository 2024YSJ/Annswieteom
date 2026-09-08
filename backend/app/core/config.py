from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"

    # Comma-separated list of allowed frontend origins for CORS. Local dev
    # only needs localhost:3000; deployed environments (Railway) must add
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
    gemini_api_key: str = ""
    llm_provider_order: str = "local,gemini"

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

    # 12-4절: 생성된 문장과 인용된 confirmed_facts 간 코사인 유사도 최소값.
    # 0.45~0.65 범위에서 실제 생성 샘플로 튜닝 — app/services/consistency_check.py 참고.
    consistency_threshold: float = 0.55

    class Config:
        env_file = ".env"


settings = Settings()
