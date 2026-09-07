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

    # 워크넷(고용24) 채용정보 Open API — 무료 즉시 발급, 조회 전용.
    # https://www.work24.go.kr 회원가입 후 Open API 메뉴에서 발급.
    worknet_api_key: str = ""
    worknet_api_base_url: str = "https://openapi.work.go.kr/opi/opi/opia/wantedApi.do"

    # 12-4절: 생성된 문장과 인용된 confirmed_facts 간 코사인 유사도 최소값.
    # 0.45~0.65 범위에서 실제 생성 샘플로 튜닝 — app/services/consistency_check.py 참고.
    consistency_threshold: float = 0.55

    class Config:
        env_file = ".env"


settings = Settings()
