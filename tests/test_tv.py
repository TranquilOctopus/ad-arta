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


# --- FrameArt.open ---------------------------------------------------------


class FakeConn:
    def __init__(self):
        self.timeouts = []
        self.closed = False

    def gettimeout(self):
        return 8

    def settimeout(self, t):
        self.timeouts.append(t)

    def close(self):
        self.closed = True


def make_art(monkeypatch, tmp_path, frames):
    """FrameArt whose base open() is faked and whose frames are scripted."""
    from samsungtvws import exceptions
    from samsungtvws.connection import SamsungTVWSConnection

    conn = FakeConn()

    def fake_open(self):
        self.connection = conn
        return conn

    monkeypatch.setattr(SamsungTVWSConnection, "open", fake_open)
    art = tv_mod.FrameArt("1.2.3.4", port=8002, token_file=str(tmp_path / "t"))
    seq = iter(frames)

    def fake_recv():
        item = next(seq)
        if item == "timeout":
            raise exceptions.ConnectionFailure("Websocket Time out")
        return item, {"event": item}

    monkeypatch.setattr(art, "_recv_frame", fake_recv)
    return art, conn


def test_frameart_ignores_client_disconnect(monkeypatch, tmp_path):
    art, conn = make_art(
        monkeypatch,
        tmp_path,
        ["ms.channel.clientDisconnect", "ms.channel.ready"],
    )
    assert art.open() is conn
    assert conn.timeouts[-1] == 8  # restored


def test_frameart_tolerates_missing_ready(monkeypatch, tmp_path):
    art, conn = make_art(monkeypatch, tmp_path, ["timeout"])
    assert art.open() is conn
    assert not conn.closed


def test_frameart_raises_on_error_event(monkeypatch, tmp_path):
    from samsungtvws import exceptions

    art, conn = make_art(monkeypatch, tmp_path, ["ms.error"])
    with pytest.raises(exceptions.ConnectionFailure):
        art.open()
    assert conn.closed
