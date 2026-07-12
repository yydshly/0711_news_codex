import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import HttpPolicy


@pytest.mark.asyncio
@respx.mock
async def test_http_policy_rejects_declared_oversized_response_before_parsing() -> None:
    respx.get("https://feed.test/large").mock(
        return_value=httpx.Response(200, headers={"content-length": "101"}, content=b"x" * 101)
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="response_too_large"):
            await HttpPolicy(client, max_response_bytes=100).get("https://feed.test/large")
