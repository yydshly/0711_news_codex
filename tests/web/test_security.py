import pytest

from newsradar.web.security import UnsafeWrite, require_loopback_host, require_same_origin


def test_local_write_rejects_remote_host() -> None:
    with pytest.raises(UnsafeWrite, match="loopback"):
        require_loopback_host("example.com")


def test_local_write_accepts_localhost_and_same_origin() -> None:
    require_loopback_host("127.0.0.1:8765")
    require_same_origin("http://127.0.0.1:8765", "127.0.0.1:8765")


def test_local_write_rejects_cross_origin() -> None:
    with pytest.raises(UnsafeWrite, match="origin"):
        require_same_origin("https://example.com", "127.0.0.1:8765")
