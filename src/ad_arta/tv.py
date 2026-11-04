"""Control the Frame TV over its local network API (port 8002)."""

from __future__ import annotations

import logging
import time

import urllib3
import websocket
from samsungtvws import SamsungTVWS, exceptions, helper
from samsungtvws.art import SamsungTVArt
from samsungtvws.connection import SamsungTVWSConnection
from samsungtvws.event import MS_CHANNEL_READY_EVENT
from wakeonlan import send_magic_packet

from .config import TVConfig

log = logging.getLogger(__name__)

CLIENT_NAME = "ad-arta"

# The TV uses a self-signed certificate; that is expected, so don't warn.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

READY_WAIT = 5.0  # seconds to wait for ms.channel.ready

NO_ART_ANSWER = (
    "The TV's Art Mode service didn't answer. The TV is reachable but its art "
    "service seems stuck; restarting the TV (unplug it for a minute) usually "
    "fixes this."
)


class FrameArt(SamsungTVArt):
    """SamsungTVArt that tolerates broadcasts before ms.channel.ready.

    The stock open() reads exactly one frame after connecting and fails unless
    it is ms.channel.ready. A real TV may first send e.g.
    ms.channel.clientDisconnect (another client left), which is not an error.
    Some older TVs (2020) never send ms.channel.ready at all.
    """

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

    def open(self):
        # Skip SamsungTVArt.open (the strict ready check), use the base one.
        SamsungTVWSConnection.open(self)
        conn = self.connection
        old_timeout = conn.gettimeout()
        deadline = time.monotonic() + READY_WAIT
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
                    return conn
                lowered = str(event).lower()
                if "error" in lowered or "unauthorized" in lowered:
                    self.close()
                    raise exceptions.ConnectionFailure(frame)
                # clientConnect/clientDisconnect and others: keep waiting
                log.debug("Ignoring event while waiting for ready: %s", event)
            log.debug("No ms.channel.ready within %.0fs, continuing", READY_WAIT)
        finally:
            if self.connection is not None:
                try:
                    self.connection.settimeout(old_timeout)
                except Exception:  # connection may have been closed above
                    pass
        return conn


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
            log.warning(NO_ART_ANSWER)
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

    def set_art_mode(self, on: bool) -> None:
        art = self._art()
        try:
            current = art.get_artmode()
            wanted = "on" if on else "off"
            if current == wanted:
                log.info("Art Mode already %s", wanted)
                return
            log.info("Turning Art Mode %s", wanted)
            art.set_artmode(wanted)
        except exceptions.ConnectionFailure as err:
            raise RuntimeError(NO_ART_ANSWER) from err
        finally:
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
