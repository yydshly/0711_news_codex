from __future__ import annotations

import os
from typing import Protocol


class CredentialProvider(Protocol):
    def require(self, name: str) -> str: ...


class EnvironmentCredentials:
    def require(self, name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise KeyError(name)
        return value
