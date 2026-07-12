from __future__ import annotations

from typing import Protocol

from newsradar.settings import Settings, get_settings


class CredentialProvider(Protocol):
    def require(self, name: str) -> str: ...


class EnvironmentCredentials:
    def require(self, name: str) -> str:
        return SettingsCredentials().require(name)


class SettingsCredentials:
    _fields = {
        "GITHUB_TOKEN": "github_token",
        "REDDIT_CLIENT_ID": "reddit_client_id",
        "REDDIT_CLIENT_SECRET": "reddit_client_secret",
        "YOUTUBE_API_KEY": "youtube_api_key",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def require(self, name: str) -> str:
        field = self._fields.get(name)
        value = getattr(self.settings, field, None) if field else None
        if value is None:
            raise KeyError(name)
        return value.get_secret_value()

    def configured_names(self) -> set[str]:
        return {
            name
            for name, field in self._fields.items()
            if getattr(self.settings, field) is not None
        }
