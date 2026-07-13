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
    event_window_hours: int = 24
    event_candidate_window_hours: int = 48
    event_model_timeout_seconds: float = 45
    event_model_max_concurrency: int = 2
    event_top_limit: int = 20
    github_token: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    youtube_api_key: SecretStr | None = None
    http_trust_env: bool = True
    http_connect_timeout_seconds: float = 10
    http_read_timeout_seconds: float = 30
    http_request_timeout_seconds: float = 45
    source_timeout_seconds: float = 120
    operation_timeout_seconds: float = 1800
    db_lock_timeout_seconds: float = 5
    worker_lease_seconds: float = 60
    worker_heartbeat_seconds: float = 15
    default_pages_per_fetch: int = 1
    max_pages_per_fetch: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
