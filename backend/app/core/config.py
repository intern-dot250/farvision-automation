from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Farvision Automation API"
    APP_ENV: str = "development"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    API_V1_PREFIX: str = "/api/v1"

    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    GOOGLE_CREDENTIALS_PATH: str = "credentials/service-account.json"
    GOOGLE_CREDENTIALS_JSON_BASE64: str = ""

    STATEMENT_MASTER_SHEET_ID: str = ""
    DEPOSIT_WITHDRAWAL_SHEET_ID: str = ""
    RECEIPT_PAYMENT_SHEET_ID: str = ""

    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
