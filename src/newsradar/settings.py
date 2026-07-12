from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    minimax_api_key: SecretStr | None = None
    minimax_base_url: str = "https://api.minimax.io"
    minimax_deep_model: str = "MiniMax-M3"
    minimax_fast_model: str = "MiniMax-M2.7-highspeed"
    github_token: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    youtube_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
