from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_env: Literal["development", "staging", "production"] = "development"
    api_log_level: str = "INFO"
    api_secret_key: str = Field(default="change_me_in_production")
    api_cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://plataforma:plataforma_dev_change_me@postgres:5432/plataforma"
    redis_url: str = "redis://redis:6379/0"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
