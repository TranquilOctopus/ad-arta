import pytest
import websocket

from ad_arta import tv as tv_mod
from ad_arta.config import TVConfig
from ad_arta.tv import FrameTV


def make_tv(tmp_path):
    return FrameTV(TVConfig(host="1.2.3.4", token_file=str(tmp_path / "t.txt")))


def test_pair_timeout_gives_friendly_error(tmp_path, monkeypatch):
    class FakeTVWS:
        def __init__(self, *a, **kw):
            pass

        def open(self):
            raise websocket.WebSocketTimeoutException("Connection timed out")

        def close(self):
            pass

    monkeypatch.setattr(tv_mod, "SamsungTVWS", FakeTVWS)
    with pytest.raises(RuntimeError, match="pair-tv"):
        make_tv(tmp_path).pair()


def test_pair_uses_long_timeout(tmp_path, monkeypatch):
    seen = {}

    class FakeTVWS:
        def __init__(self, *a, **kw):
            seen.update(kw)

        def open(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(tv_mod, "SamsungTVWS", FakeTVWS)
    make_tv(tmp_path).pair()
    assert seen["timeout"] == 60
