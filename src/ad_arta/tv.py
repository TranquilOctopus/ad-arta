"""Control the Frame TV over its local network API (port 8002)."""

from __future__ import annotations

import logging
import time

import urllib3
import websocket
from samsungtvws import SamsungTVWS, exceptions, helper
from samsungtvws.art import SamsungTVArt
from samsungtvws.connection import SamsungTVWSConnection
from samsungtvws.event import D2D_SERVICE_MESSAGE_EVENT, MS_CHANNEL_READY_EVENT
from wakeonlan import send_magic_packet

from .config import TVConfig

log = logging.getLogger(__name__)

CLIENT_NAME = "ad-arta"

# The TV uses a self-signed certificate; that is expected, so don't warn.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Seconds to wait for ms.channel.ready. Right after a restart or wake the art
# service can join the channel several seconds late (7s seen on a 2020 Frame),
# and requests sent before then are lost. Ready usually arrives at once.
READY_WAIT = 15.0

# When switching Art Mode: how long to wait for the art service before
# pressing the power key to wake it, and how long to wait after pressing it.
# The service rejoined ~7s after a power key press on a 2020 Frame.
READY_WAIT_BEFORE_WAKE = 8.0
WAKE_WAIT = 20.0
REMOTE_WAKE_TIMEOUT = 20.0

NOT_RUNNING = (
    "The TV's Art Mode service isn't running right now (the TV stops it after "
    "a while). art-on and art-off start it again by pressing the power key."
)
DID_NOT_START = (
    "The TV's Art Mode service didn't start, even after pressing the power "
    "key. Restarting the TV (unplug it for a minute) usually fixes this."
)
NO_ART_ANSWER = (
    "The TV's Art Mode service stopped answering. Try again; if it keeps "
    "happening, restart the TV (unplug it for a minute)."
)


class FrameArt(SamsungTVArt):
    """SamsungTVArt that tolerates broadcasts before ms.channel.ready.

    The stock open() reads exactly one frame after connecting and fails unless
    it is ms.channel.ready. A real TV may first send e.g.
    ms.channel.clientDisconnect (another client left), which is not an error.
    ms.channel.ready only arrives once the TV's art service is on the channel.
    The Frame stops that service after a while; `ready` says whether it is
    there.
    """

    ready = False

    def _recv_frame(self):
        """Receive one frame, giving up after the socket timeout in total.

        websocket-client's recv() answers pings itself and then starts a fresh
        read with the full timeout. The Frame pings every ~6s, so with an 8s
        timeout recv() never times out when the art service stays silent.
        Here pings are handled one by one against a single deadline.
        """
        conn = self.connection
        assert conn
        budget = conn.gettimeout()
        deadline = None if budget is None else time.monotonic() + budget
        try:
            while True:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise exceptions.ConnectionFailure("Websocket Time out")
                    conn.settimeout(remaining)
                try:
                    opcode, frame = conn.recv_data_frame(control_frame=True)
                except websocket.WebSocketTimeoutException as err:
                    raise exceptions.ConnectionFailure(
                        f"Websocket Time out: {err}"
                    ) from err
                except (websocket.WebSocketException, OSError) as err:
                    # e.g. the TV drops connections while switching modes
                    raise exceptions.ConnectionFailure(
                        f"Lost connection to the TV: {err}"
                    ) from err
                if opcode in (websocket.ABNF.OPCODE_PING, websocket.ABNF.OPCODE_PONG):
                    continue  # already answered by websocket-client
                if opcode == websocket.ABNF.OPCODE_CLOSE:
                    raise exceptions.ConnectionFailure("TV closed the connection")
                raw = frame.data
                if opcode == websocket.ABNF.OPCODE_TEXT and isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                break
        finally:
            if self.connection is not None:
                try:
                    self.connection.settimeout(budget)
                except Exception:
                    pass
        response = helper.process_api_response(raw)
        event = response.get("event", "*")
        self._websocket_event(event, response)
        return event, response

    def open(self, ready_wait: float = READY_WAIT):
        # Skip SamsungTVArt.open (the strict ready check), use the base one.
        SamsungTVWSConnection.open(self)
        self.ready = False
        self.wait_ready(ready_wait)
        return self.connection

    def wait_ready(self, seconds: float) -> bool:
        """Wait up to `seconds` for ms.channel.ready. Return self.ready."""
        if self.ready:
            return True
        conn = self.connection
        old_timeout = conn.gettimeout()
        deadline = time.monotonic() + seconds
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                conn.settimeout(remaining)
                try:
                    event, frame = self._recv_frame()
                except exceptions.ConnectionFailure:  # websocket timeout
                    break
                if event == MS_CHANNEL_READY_EVENT:
                    self.ready = True
                    return True
                lowered = str(event).lower()
                if "error" in lowered or "unauthorized" in lowered:
                    self.close()
                    raise exceptions.ConnectionFailure(frame)
                # clientConnect/clientDisconnect and others: keep waiting
                log.debug("Ignoring event while waiting for ready: %s", event)
            log.debug("No ms.channel.ready within %.0fs, continuing", seconds)
            return False
        finally:
            if self.connection is not None:
                try:
                    self.connection.settimeout(old_timeout)
                except Exception:  # connection may have been closed above
                    pass

    def set_artmode_confirmed(self, wanted: str) -> None:
        """Set Art Mode and wait until the TV confirms it.

        Turning Art Mode on, the Frame sends no reply carrying our request id,
        only an art_mode_changed broadcast, so the stock set_artmode() waits
        until it times out. Accept either as confirmation.
        """
        req_id = self._new_request_uuid()
        self._send_art_request(
            {"request": "set_artmode_status", "value": wanted},
            wait_for_event=None,
            request_uuid=req_id,
        )
        conn = self.connection
        old_timeout = conn.gettimeout()
        deadline = time.monotonic() + (self.timeout or READY_WAIT)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise exceptions.ConnectionFailure("Websocket Time out")
                conn.settimeout(remaining)
                event, frame = self._recv_frame()
                if event != D2D_SERVICE_MESSAGE_EVENT:
                    continue
                payload = self._decode_d2d_payload(frame) or {}
                sub_event = payload.get("event")
                if sub_event == "error":
                    raise exceptions.ResponseError(
                        "set_artmode_status failed with error number "
                        f"{payload.get('error_code', 'unknown')}"
                    )
                if payload.get("request_id", payload.get("id")) == req_id:
                    return
                if sub_event == "art_mode_changed" and payload.get("status") == wanted:
                    return
        finally:
            if self.connection is not None:
                try:
                    self.connection.settimeout(old_timeout)
                except Exception:
                    pass


class FrameTV:
    """Blocking client. Run its methods in a worker thread from async code."""

    def __init__(self, cfg: TVConfig, wake_timeout: float = 30.0) -> None:
        self.cfg = cfg
        self.wake_timeout = wake_timeout

    def _remote(self, timeout: float = 8) -> SamsungTVWS:
        return SamsungTVWS(
            self.cfg.host,
            port=8002,
            token_file=self.cfg.token_file,
            timeout=timeout,
            name=CLIENT_NAME,
        )

    def _art(self, timeout: float = 8) -> FrameArt:
        # Same arguments SamsungTVWS.art() passes to SamsungTVArt.
        return FrameArt(
            self.cfg.host,
            port=8002,
            token_file=self.cfg.token_file,
            timeout=timeout,
            name=CLIENT_NAME,
        )

    # --- state -----------------------------------------------------------

    def power_state(self) -> str:
        """Return "on", "standby" or "off" (unreachable)."""
        try:
            info = self._remote().rest_device_info()
        except Exception:  # network errors, timeouts
            return "off"
        state = str(info.get("device", {}).get("PowerState", "on")).lower()
        return "standby" if state == "standby" else "on"

    def art_mode(self) -> str | None:
        """Return "on"/"off", or None if it can't be read."""
        art = self._art()
        try:
            return art.get_artmode()
        except exceptions.ConnectionFailure:
            log.warning(NOT_RUNNING)
            return None
        finally:
            art.close()

    # --- actions ---------------------------------------------------------

    def ensure_on(self) -> None:
        """Wake the TV with Wake-on-LAN if it is off or in standby."""
        if self.power_state() == "on":
            return
        if not self.cfg.mac:
            raise RuntimeError(
                "TV is off and no [tv] mac is set, so it can't be woken up"
            )
        log.info("TV is off, sending Wake-on-LAN")
        deadline = time.monotonic() + self.wake_timeout
        while time.monotonic() < deadline:
            send_magic_packet(self.cfg.mac)
            time.sleep(2)
            if self.power_state() == "on":
                time.sleep(3)  # let the art service start
                return
        raise RuntimeError("TV did not wake up")

    def _press_power(self) -> None:
        # On The Frame a short power press switches between TV and Art Mode
        # (it does not turn the TV off) and restarts a stopped art service.
        # While the art service is stopped the remote channel can take 10s+
        # to answer, so give it longer than the usual 8s.
        remote = self._remote(timeout=REMOTE_WAKE_TIMEOUT)
        try:
            remote.send_key("KEY_POWER")
        finally:
            remote.close()

    def _open_art_when_ready(self, seconds: float) -> FrameArt | None:
        """Keep connecting to the art channel until the service is there.

        After a power key press the TV may drop connections and be briefly
        unreachable, so reconnect instead of waiting on one connection.
        """
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            art = self._art()
            try:
                art.open(ready_wait=min(remaining, READY_WAIT_BEFORE_WAKE))
                if art.ready:
                    return art
            except (exceptions.ConnectionFailure, websocket.WebSocketException, OSError) as err:
                log.debug("Art channel not available yet: %s", err)
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
            art.close()

    def set_art_mode(self, on: bool) -> None:
        wanted = "on" if on else "off"
        art = self._art()
        try:
            art.open(ready_wait=READY_WAIT_BEFORE_WAKE)
            if not art.ready:
                # The power press may flip Art Mode the wrong way; the state is
                # read and set explicitly below, so it ends up right either way.
                log.info("Art Mode service isn't running, pressing power to wake it")
                art.close()
                self._press_power()
                art = self._open_art_when_ready(WAKE_WAIT)
                if art is None:
                    raise RuntimeError(DID_NOT_START)
            current = art.get_artmode()
            if current == wanted:
                log.info("Art Mode already %s", wanted)
                return
            log.info("Turning Art Mode %s", wanted)
            art.set_artmode_confirmed(wanted)
        except (exceptions.ConnectionFailure, websocket.WebSocketException, OSError) as err:
            raise RuntimeError(NO_ART_ANSWER) from err
        finally:
            if art is not None:
                art.close()

    def go_to_art(self) -> None:
        self.ensure_on()
        self.set_art_mode(True)

    def go_to_tv(self) -> None:
        self.ensure_on()
        self.set_art_mode(False)
        if self.cfg.input_key:
            time.sleep(1)
            remote = self._remote()
            try:
                remote.send_key(self.cfg.input_key)
            finally:
                remote.close()

    def pair(self) -> None:
        """Open a connection so the TV shows its "Allow" prompt."""
        wait = 60
        host = self.cfg.host
        try:
            remote = self._remote(timeout=wait)
            remote.open()
            remote.close()
        except (websocket.WebSocketTimeoutException, TimeoutError) as err:
            raise RuntimeError(
                f"No answer on the TV within {wait} seconds. Run `ad-arta pair-tv` "
                "again and choose Allow on the TV (if you already pressed Allow, "
                "the second run usually succeeds right away)."
            ) from err
        except OSError as err:  # includes ConnectionError
            raise RuntimeError(
                f"Couldn't reach the TV at {host}. Check the IP address and "
                "that the TV is on."
            ) from err
