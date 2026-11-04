"""Watch the Apple TV's power state with pyatv and keep the connection alive."""

from __future__ import annotations

import asyncio
import logging

import pyatv
from pyatv.const import PowerState
from pyatv.interface import DeviceListener, PowerListener
from pyatv.storage.file_storage import FileStorage

from .bridge import Bridge
from .config import AppleTVConfig

log = logging.getLogger(__name__)


class AppleTVWatcher(PowerListener, DeviceListener):
    def __init__(self, cfg: AppleTVConfig, bridge: Bridge) -> None:
        self.cfg = cfg
        self.bridge = bridge
        self._disconnected = asyncio.Event()

    # pyatv callbacks
    def powerstate_update(self, old_state: PowerState, new_state: PowerState) -> None:
        self._report(new_state)

    def connection_lost(self, exception: Exception) -> None:
        log.warning("Lost connection to Apple TV: %s", exception)
        self._disconnected.set()

    def connection_closed(self) -> None:
        self._disconnected.set()

    def _report(self, state: PowerState) -> None:
        if state == PowerState.On:
            self.bridge.appletv_power_changed(True)
        elif state == PowerState.Off:
            self.bridge.appletv_power_changed(False)

    async def _find(self, loop, storage):
        kwargs = {"storage": storage}
        if self.cfg.identifier:
            kwargs["identifier"] = self.cfg.identifier
        if self.cfg.host:
            kwargs["hosts"] = [self.cfg.host]
        devices = await pyatv.scan(loop, **kwargs)
        return devices[0] if devices else None

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        # Same credential file that `atvremote` writes when you pair.
        storage = FileStorage.default_storage(loop)
        await storage.load()
        backoff = 5
        while True:
            atv = None
            try:
                conf = await self._find(loop, storage)
                if conf is None:
                    raise RuntimeError("Apple TV not found on the network")
                atv = await pyatv.connect(conf, loop, storage=storage)
                log.info("Connected to %s", conf.name)
                backoff = 5
                self._disconnected.clear()
                atv.listener = self
                atv.power.listener = self
                self._report(atv.power.power_state)
                await self._disconnected.wait()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Apple TV connection problem: %s", exc)
            finally:
                if atv is not None:
                    atv.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
