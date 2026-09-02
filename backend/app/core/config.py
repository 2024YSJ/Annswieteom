from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"

    database_url: str
    jwt_secret: str
    jwt_access_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 14

    local_llm_base_url: str = "http://localhost:11434"
    local_llm_model_name: str = "exaone3.5:7.8b"
    gemini_api_key: str = ""
    llm_provider_order: str = "local,gemini"

    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_storage_bucket: str = "records"

    class Config:
        env_file = ".env"


settings = Settings()
