"""Turn Apple TV power changes into Frame TV actions."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

log = logging.getLogger(__name__)


class TV(Protocol):
    def go_to_art(self) -> None: ...
    def go_to_tv(self) -> None: ...


class Bridge:
    def __init__(self, tv: TV, off_delay: float = 2.0, wake_tv: bool = True) -> None:
        self.tv = tv
        self.off_delay = off_delay
        self.wake_tv = wake_tv
        self._appletv_on: bool | None = None
        self._pending: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def appletv_power_changed(self, on: bool) -> None:
        """Called on every power report, including the first one after (re)connecting.

        The first report ever only records the state. After that, only real
        changes trigger an action, so a reconnect doesn't fight a user who is,
        say, watching a TV app with the Samsung remote.
        """
        previous, self._appletv_on = self._appletv_on, on
        if previous is None or previous == on:
            return
        log.info("Apple TV turned %s", "on" if on else "off")
        if self._pending and not self._pending.done():
            self._pending.cancel()
        self._pending = asyncio.ensure_future(self._apply(on))

    async def _apply(self, on: bool) -> None:
        try:
            if on:
                if not self.wake_tv:
                    return
                action = self.tv.go_to_tv
            else:
                await asyncio.sleep(self.off_delay)
                action = self.tv.go_to_art
            async with self._lock:
                await asyncio.to_thread(action)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Could not update the TV")

    async def wait_idle(self) -> None:
        if self._pending:
            await asyncio.gather(self._pending, return_exceptions=True)
