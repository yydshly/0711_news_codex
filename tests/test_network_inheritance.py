import pytest

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.safe_http import new_safe_probe_client
from newsradar.research.probes.youtube import _create_transcript_session
from newsradar.settings import Settings


@pytest.mark.asyncio
async def test_default_clients_inherit_system_network_by_default(monkeypatch) -> None:
    settings = Settings(http_trust_env=True)
    monkeypatch.setattr("newsradar.ingestion.fetchers.base.get_settings", lambda: settings)
    monkeypatch.setattr("newsradar.research.probes.safe_http.get_settings", lambda: settings)
    monkeypatch.setattr("newsradar.research.probes.youtube.get_settings", lambda: settings)
    policy = HttpPolicy.default()
    probe_client = new_safe_probe_client()
    transcript_session = _create_transcript_session()
    try:
        assert policy.client.trust_env is True
        assert probe_client.trust_env is True
        assert transcript_session.trust_env is True
        assert list(probe_client.cookies.jar) == []
        assert transcript_session.cookies.get_dict() == {}
    finally:
        await policy.client.aclose()
        await probe_client.aclose()
        transcript_session.close()


@pytest.mark.asyncio
async def test_http_trust_env_false_is_an_explicit_diagnostic_override(monkeypatch) -> None:
    settings = Settings(http_trust_env=False)
    monkeypatch.setattr("newsradar.ingestion.fetchers.base.get_settings", lambda: settings)
    monkeypatch.setattr("newsradar.research.probes.safe_http.get_settings", lambda: settings)
    policy = HttpPolicy.default()
    probe_client = new_safe_probe_client()
    try:
        assert policy.client.trust_env is False
        assert probe_client.trust_env is False
    finally:
        await policy.client.aclose()
        await probe_client.aclose()
