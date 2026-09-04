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

    # One-time migration seed only - read once to seed app_config's password
    # hash on first deploy after this feature shipped (see
    # app_config_repository.seed_password_if_empty). Never read at request
    # time; the live dashboard password lives in Supabase (app_config table)
    # so it can be reset without an env var edit or redeploy.
    ACCESS_PASSWORD: str = ""

    # Static secret so the frontend's /api/clear-sheet proxy route can prove
    # to the backend it's acting on behalf of a logged-in session, without
    # ever exposing anything password-related to the browser. Deliberately
    # independent of the (now resettable) dashboard password.
    INTERNAL_API_SECRET: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
