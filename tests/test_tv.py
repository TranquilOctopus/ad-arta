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


# --- FrameArt._recv_frame --------------------------------------------------


class Frame:
    def __init__(self, data):
        self.data = data


class PingingConn:
    """Answers every read with a ping, like a TV whose art service is silent."""

    def __init__(self, frames=None):
        self.timeout = 0.3
        self.frames = list(frames or [])

    def gettimeout(self):
        return self.timeout

    def settimeout(self, t):
        self.timeout = t

    def recv_data_frame(self, control_frame=False):
        import time

        if self.frames:
            return self.frames.pop(0)
        time.sleep(0.05)
        return websocket.ABNF.OPCODE_PING, Frame(b"\x00")


def art_with_conn(tmp_path, conn):
    art = tv_mod.FrameArt("1.2.3.4", port=8002, token_file=str(tmp_path / "t"))
    art.connection = conn
    return art


def test_recv_frame_times_out_despite_pings(tmp_path):
    import time

    from samsungtvws import exceptions

    conn = PingingConn()
    art = art_with_conn(tmp_path, conn)
    start = time.monotonic()
    with pytest.raises(exceptions.ConnectionFailure):
        art._recv_frame()
    assert time.monotonic() - start < 1
    assert conn.timeout == 0.3  # restored


def test_recv_frame_skips_pings_and_returns_event(tmp_path):
    frames = [
        (websocket.ABNF.OPCODE_PING, Frame(b"\x00")),
        (websocket.ABNF.OPCODE_TEXT, Frame(b'{"event": "d2d_service_message"}')),
    ]
    art = art_with_conn(tmp_path, PingingConn(frames))
    event, frame = art._recv_frame()
    assert event == "d2d_service_message"


def test_art_mode_returns_none_when_art_service_silent(tmp_path, monkeypatch):
    from samsungtvws import exceptions

    class SilentArt:
        def get_artmode(self):
            raise exceptions.ConnectionFailure("Websocket Time out")

        def close(self):
            pass

    tv = make_tv(tmp_path)
    monkeypatch.setattr(tv, "_art", lambda: SilentArt())
    assert tv.art_mode() is None


# --- FrameArt.set_artmode_confirmed / wait_ready --------------------------


def d2d(payload):
    import json

    return "d2d_service_message", {
        "event": "d2d_service_message",
        "data": json.dumps(payload),
    }


def scripted_art(tmp_path, monkeypatch, frames):
    """FrameArt on a fake connection that returns `frames`, then times out."""
    from samsungtvws import exceptions

    art = tv_mod.FrameArt(
        "1.2.3.4", port=8002, token_file=str(tmp_path / "t"), timeout=8
    )
    art.connection = FakeConn()
    sent = []
    seq = iter(frames)

    def fake_send(request_data, wait_for_event=None, request_uuid=None, **kw):
        sent.append((request_data, wait_for_event, request_uuid))

    def fake_recv():
        try:
            item = next(seq)
        except StopIteration:
            raise exceptions.ConnectionFailure("Websocket Time out")
        return item(sent[-1][2]) if callable(item) else item

    monkeypatch.setattr(art, "_send_art_request", fake_send)
    monkeypatch.setattr(art, "_recv_frame", fake_recv)
    return art, sent


def test_set_artmode_accepts_art_mode_changed_broadcast(tmp_path, monkeypatch):
    # What a 2020 Frame sends when turning Art Mode on: no request id.
    art, sent = scripted_art(
        tmp_path,
        monkeypatch,
        [d2d({"event": "art_mode_changed", "status": "on"})],
    )
    art.set_artmode_confirmed("on")
    request, wait_for_event, _ = sent[0]
    assert request == {"request": "set_artmode_status", "value": "on"}
    assert wait_for_event is None


def test_set_artmode_accepts_reply_with_request_id(tmp_path, monkeypatch):
    art, _ = scripted_art(
        tmp_path,
        monkeypatch,
        [lambda rid: d2d({"event": "set_artmode_status", "id": rid})],
    )
    art.set_artmode_confirmed("off")


def test_set_artmode_ignores_unrelated_messages(tmp_path, monkeypatch):
    from samsungtvws import exceptions

    art, _ = scripted_art(
        tmp_path,
        monkeypatch,
        [
            ("ms.channel.clientConnect", {"event": "ms.channel.clientConnect"}),
            d2d({"event": "image_selected", "content_id": "MY_F0025"}),
            d2d({"event": "art_mode_changed", "status": "off"}),
            d2d({"event": "set_artmode_status", "id": "someone-else"}),
        ],
    )
    with pytest.raises(exceptions.ConnectionFailure):
        art.set_artmode_confirmed("on")
    assert art.connection.timeouts[-1] == 8  # restored


def test_set_artmode_raises_on_error_reply(tmp_path, monkeypatch):
    from samsungtvws import exceptions

    art, _ = scripted_art(
        tmp_path, monkeypatch, [d2d({"event": "error", "error_code": "-1"})]
    )
    with pytest.raises(exceptions.ResponseError):
        art.set_artmode_confirmed("on")


def test_open_sets_ready_flag(monkeypatch, tmp_path):
    art, _ = make_art(monkeypatch, tmp_path, ["ms.channel.ready"])
    art.open()
    assert art.ready


def test_open_without_ready_then_wait_ready(monkeypatch, tmp_path):
    art, _ = make_art(
        monkeypatch,
        tmp_path,
        ["timeout", "ms.channel.clientConnect", "ms.channel.ready"],
    )
    art.open()
    assert not art.ready
    assert art.wait_ready(5)
    assert art.ready


# --- FrameTV.set_art_mode ----------------------------------------------------


class FakeArt:
    """Stands in for FrameArt. `ready_after_power` decides if a press helps."""

    def __init__(self, tv, ready=True, ready_after_power=True, mode="off",
                 get_fails=False):
        self.tv = tv
        self.ready = ready
        self.ready_after_power = ready_after_power
        self.mode = mode
        self.get_fails = get_fails
        self.opened_with = None
        self.set_calls = []
        self.closed = False

    def open(self, ready_wait):
        self.opened_with = ready_wait

    def wait_ready(self, seconds):
        if self.tv.power_presses and self.ready_after_power:
            self.ready = True
        return self.ready

    def get_artmode(self):
        from samsungtvws import exceptions

        if self.get_fails:
            raise exceptions.ConnectionFailure("Websocket Time out")
        return self.mode

    def set_artmode_confirmed(self, wanted):
        self.set_calls.append(wanted)

    def close(self):
        self.closed = True


def tv_with_fake_art(tmp_path, monkeypatch, **art_kw):
    tv = make_tv(tmp_path)
    tv.power_presses = 0

    def press():
        tv.power_presses += 1

    art = FakeArt(tv, **art_kw)
    monkeypatch.setattr(tv, "_art", lambda: art)
    monkeypatch.setattr(tv, "_press_power", press)
    return tv, art


def test_set_art_mode_when_service_running(tmp_path, monkeypatch):
    tv, art = tv_with_fake_art(tmp_path, monkeypatch, ready=True, mode="off")
    tv.set_art_mode(True)
    assert art.set_calls == ["on"]
    assert tv.power_presses == 0
    assert art.closed


def test_set_art_mode_already_in_wanted_state(tmp_path, monkeypatch):
    tv, art = tv_with_fake_art(tmp_path, monkeypatch, ready=True, mode="on")
    tv.set_art_mode(True)
    assert art.set_calls == []


def test_set_art_mode_wakes_stopped_service_with_power_key(tmp_path, monkeypatch):
    tv, art = tv_with_fake_art(tmp_path, monkeypatch, ready=False, mode="off")
    tv.set_art_mode(True)
    assert art.opened_with == tv_mod.READY_WAIT_BEFORE_WAKE
    assert tv.power_presses == 1
    assert art.set_calls == ["on"]


def test_set_art_mode_after_power_key_flipped_it_already(tmp_path, monkeypatch):
    # The press itself switched to Art Mode: nothing more to send.
    tv, art = tv_with_fake_art(tmp_path, monkeypatch, ready=False, mode="on")
    tv.set_art_mode(True)
    assert tv.power_presses == 1
    assert art.set_calls == []


def test_set_art_mode_service_never_starts(tmp_path, monkeypatch):
    tv, art = tv_with_fake_art(
        tmp_path, monkeypatch, ready=False, ready_after_power=False
    )
    with pytest.raises(RuntimeError, match="didn't start"):
        tv.set_art_mode(True)
    assert tv.power_presses == 1
    assert art.set_calls == []
    assert art.closed


def test_set_art_mode_gives_friendly_error_when_service_stops_answering(
    tmp_path, monkeypatch
):
    tv, art = tv_with_fake_art(tmp_path, monkeypatch, ready=True, get_fails=True)
    with pytest.raises(RuntimeError, match="stopped answering"):
        tv.set_art_mode(True)
    assert tv.power_presses == 0
