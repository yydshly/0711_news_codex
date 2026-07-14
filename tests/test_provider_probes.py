import httpx
import pytest

from newsradar.providers.probes import ProviderProbe, probe_providers
from newsradar.providers.schema import ProviderDefinition

from .test_provider_schema import valid_provider


class _Credentials:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    def configured_names(self) -> set[str]:
        return self.names


def provider(**updates) -> ProviderDefinition:
    data = valid_provider()
    data.update(updates)
    return ProviderDefinition.model_validate(data)


@pytest.mark.asyncio
async def test_paid_provider_is_blocked_without_network_request() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProviderProbe(client).probe(
            provider(
                id="x",
                name="X",
                availability="requires_payment",
                auth_mode="paid",
                cost_tier="paid",
                unlock_requirements=["Purchase API credits"],
            )
        )

    assert result.outcome == "blocked"
    assert result.availability == "requires_payment"
    assert requests == 0


@pytest.mark.asyncio
async def test_missing_required_env_is_blocked(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    async with httpx.AsyncClient() as client:
        result = await ProviderProbe(client, credentials=_Credentials(set())).probe(
            provider(
                id="youtube",
                name="YouTube",
                availability="requires_credentials",
                auth_mode="api_key",
                cost_tier="free_quota",
                required_env=["YOUTUBE_API_KEY"],
                unlock_requirements=["Create a Google API key"],
            )
        )

    assert result.outcome == "blocked"
    assert "YOUTUBE_API_KEY" in result.reason


@pytest.mark.asyncio
async def test_settings_backed_credentials_allow_capability_probe_without_os_env(
    monkeypatch,
) -> None:
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProviderProbe(
            client, credentials=_Credentials({"YOUTUBE_API_KEY"})
        ).probe(
            provider(
                id="youtube",
                name="YouTube",
                availability="requires_credentials",
                auth_mode="api_key",
                cost_tier="free_quota",
                required_env=["YOUTUBE_API_KEY"],
                unlock_requirements=["Create a Google API key"],
            )
        )

    assert result.outcome == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "outcome"),
    [(200, "success"), (401, "blocked"), (403, "blocked"), (429, "blocked"), (500, "failed")],
)
async def test_capability_probe_maps_http_status(status: int, outcome: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProviderProbe(client).probe(provider())

    assert result.outcome == outcome
    assert result.http_status == status
    assert result.probe_type == "capability"


@pytest.mark.asyncio
async def test_provider_batch_isolates_failures() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if "docs.bsky.app" in request.url.host:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await probe_providers(
            [provider(), provider(id="x", name="X", docs_url="https://docs.x.com/")], client
        )

    assert set(results) == {"bluesky", "x"}
    assert results["bluesky"].outcome == "failed"
    assert results["x"].outcome == "success"
