from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "evalbench"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"

    # Timeouts (seconds)
    default_request_timeout: int = 120
    suite_run_timeout: int = 900

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Authentication
    secret_key: str = "change-this-to-a-random-32-char-string"
    token_expire_minutes: int = 10080
    admin_username: str = "admin"
    admin_password: str = "change-me-in-production"
    admin_api_key: str = "eb_admin_change_me_in_production"

    # CORS
    cors_origins: str = "http://localhost:8501,http://localhost:3000"

    # Application
    log_level: str = "INFO"


settings = Settings()
