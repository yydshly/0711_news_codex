from __future__ import annotations

from newsradar.credentials import CredentialProvider, SettingsCredentials

__all__ = ["CredentialProvider", "EnvironmentCredentials", "SettingsCredentials"]


class EnvironmentCredentials(SettingsCredentials):
    """Legacy fetcher name retained while all values come from Settings."""
