"""Control the Frame TV over its local network API (port 8002)."""

from __future__ import annotations

import logging
import time

import websocket
from samsungtvws import SamsungTVWS
from wakeonlan import send_magic_packet

from .config import TVConfig

log = logging.getLogger(__name__)

CLIENT_NAME = "ad-arta"


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
        art = self._remote().art()
        try:
            return art.get_artmode()
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
        art = self._remote().art()
        try:
            current = art.get_artmode()
            wanted = "on" if on else "off"
            if current == wanted:
                log.info("Art Mode already %s", wanted)
                return
            log.info("Turning Art Mode %s", wanted)
            art.set_artmode(wanted)
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
