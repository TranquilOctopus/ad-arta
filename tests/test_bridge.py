import asyncio

from ad_arta.bridge import Bridge


class FakeTV:
    def __init__(self):
        self.calls = []

    def go_to_art(self):
        self.calls.append("art")

    def go_to_tv(self):
        self.calls.append("tv")


def run(coro):
    return asyncio.run(coro)


def test_first_report_only_records_state():
    async def scenario():
        tv = FakeTV()
        b = Bridge(tv, off_delay=0)
        b.appletv_power_changed(False)
        await b.wait_idle()
        return tv.calls

    assert run(scenario()) == []


def test_sleep_goes_to_art_and_wake_goes_to_tv():
    async def scenario():
        tv = FakeTV()
        b = Bridge(tv, off_delay=0)
        b.appletv_power_changed(True)
        b.appletv_power_changed(False)
        await b.wait_idle()
        b.appletv_power_changed(True)
        await b.wait_idle()
        return tv.calls

    assert run(scenario()) == ["art", "tv"]


def test_quick_wake_cancels_art_mode():
    async def scenario():
        tv = FakeTV()
        b = Bridge(tv, off_delay=0.2)
        b.appletv_power_changed(True)
        b.appletv_power_changed(False)
        await asyncio.sleep(0.05)
        b.appletv_power_changed(True)
        await b.wait_idle()
        return tv.calls

    assert run(scenario()) == ["tv"]


def test_repeated_reports_do_nothing():
    async def scenario():
        tv = FakeTV()
        b = Bridge(tv, off_delay=0)
        for _ in range(3):
            b.appletv_power_changed(True)
        await b.wait_idle()
        return tv.calls

    assert run(scenario()) == []


def test_wake_tv_can_be_disabled():
    async def scenario():
        tv = FakeTV()
        b = Bridge(tv, off_delay=0, wake_tv=False)
        b.appletv_power_changed(False)
        b.appletv_power_changed(True)
        await b.wait_idle()
        return tv.calls

    assert run(scenario()) == []


def test_tv_errors_are_logged_not_raised():
    class BrokenTV(FakeTV):
        def go_to_art(self):
            raise OSError("TV unreachable")

    async def scenario():
        b = Bridge(BrokenTV(), off_delay=0)
        b.appletv_power_changed(True)
        b.appletv_power_changed(False)
        await b.wait_idle()

    run(scenario())
