"""Command line entry point: `ad-arta <command>`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from .config import load_config
from .tv import FrameTV


def _run(cfg) -> None:
    from .appletv import AppleTVWatcher
    from .bridge import Bridge

    bridge = Bridge(
        FrameTV(cfg.tv),
        off_delay=cfg.bridge.off_delay,
        wake_tv=cfg.bridge.wake_tv_with_appletv,
    )
    asyncio.run(AppleTVWatcher(cfg.appletv, bridge).run_forever())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ad-arta", description="Frame TV Art Mode bridge for Apple TV")
    parser.add_argument("-c", "--config", help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--log-file", help="append log output to this file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="watch the Apple TV and drive the Frame TV")
    sub.add_parser("pair-tv", help="connect once so you can press Allow on the TV")
    sub.add_parser("status", help="show TV power and Art Mode state")
    sub.add_parser("art-on", help="switch the TV to Art Mode now")
    sub.add_parser("art-off", help="switch the TV from Art Mode to TV now")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=args.log_file,
        encoding="utf-8",
    )
    cfg = load_config(args.config)
    tv = FrameTV(cfg.tv)

    if args.command == "run":
        try:
            _run(cfg)
        except KeyboardInterrupt:
            pass
    elif args.command == "pair-tv":
        print("Look at the TV and choose Allow...")
        try:
            tv.pair()
        except RuntimeError as err:
            raise SystemExit(str(err))
        if os.path.exists(cfg.tv.token_file):
            print(f"Paired. Token saved to {cfg.tv.token_file}")
        else:
            raise SystemExit(
                "The TV accepted the connection but sent no token, so it will "
                "ask to Allow again on every connection and switching Art Mode "
                "can fail. Run `ad-arta pair-tv` again and choose Allow on the "
                "TV. If it keeps happening, see \"TV asks to Allow again\" in "
                "the README."
            )
    elif args.command == "status":
        power = tv.power_state()
        print(f"TV power: {power}")
        if power == "on":
            print(f"Art Mode: {tv.art_mode()}")
    elif args.command in ("art-on", "art-off"):
        action = tv.go_to_art if args.command == "art-on" else tv.go_to_tv
        try:
            action()
        except RuntimeError as err:
            raise SystemExit(str(err))


if __name__ == "__main__":
    main()
