import pytest

from newsradar.web.security import (
    UnsafeWrite,
    consume_one_time_token,
    require_loopback_host,
    require_same_origin,
)


def test_local_write_rejects_remote_host() -> None:
    with pytest.raises(UnsafeWrite, match="loopback"):
        require_loopback_host("example.com")


def test_local_write_accepts_localhost_and_same_origin() -> None:
    require_loopback_host("127.0.0.1:8765")
    require_same_origin("http://127.0.0.1:8765", "127.0.0.1:8765")


def test_local_write_rejects_cross_origin() -> None:
    with pytest.raises(UnsafeWrite, match="origin"):
        require_same_origin("https://example.com", "127.0.0.1:8765")


def test_local_write_accepts_opaque_origin_only_for_same_origin_browser_context() -> None:
    require_same_origin(
        "null",
        "127.0.0.1:8765",
        fetch_site="same-origin",
    )


@pytest.mark.parametrize("fetch_site", [None, "cross-site", "same-site"])
def test_local_write_rejects_opaque_origin_without_same_origin_context(
    fetch_site: str | None,
) -> None:
    with pytest.raises(UnsafeWrite, match="origin"):
        require_same_origin("null", "127.0.0.1:8765", fetch_site=fetch_site)


def test_local_write_rejects_opaque_origin_for_non_loopback_host() -> None:
    with pytest.raises(UnsafeWrite, match="loopback"):
        require_same_origin("null", "example.com", fetch_site="same-origin")


def test_one_time_token_cannot_be_reused() -> None:
    state = {"tokens": ["first"]}
    consume_one_time_token(state, "first")
    with pytest.raises(UnsafeWrite, match="token"):
        consume_one_time_token(state, "first")
