"""Load settings from a TOML file."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_PATHS = [Path("config.toml"), Path("/etc/ad-arta/config.toml")]


@dataclass
class TVConfig:
    host: str
    mac: str = ""
    token_file: str = "tv-token.txt"
    input_key: str = ""


@dataclass
class AppleTVConfig:
    identifier: str = ""
    host: str = ""


@dataclass
class BridgeConfig:
    off_delay: float = 2.0
    wake_tv_with_appletv: bool = True


@dataclass
class Config:
    tv: TVConfig
    appletv: AppleTVConfig = field(default_factory=AppleTVConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)


def find_config(path: str | None) -> Path:
    if path:
        return Path(path)
    for candidate in DEFAULT_PATHS:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "No config found. Copy config.example.toml to config.toml "
        "or pass --config /path/to/config.toml"
    )


def load_config(path: str | None = None) -> Config:
    config_path = find_config(path)
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    if "tv" not in raw or not raw["tv"].get("host"):
        raise SystemExit(f"{config_path}: [tv] host is required")

    tv = TVConfig(**raw["tv"])
    # A relative token path is relative to the config file, not the cwd.
    token = Path(tv.token_file).expanduser()
    if not token.is_absolute():
        token = config_path.parent.resolve() / token
    tv.token_file = str(token)

    return Config(
        tv=tv,
        appletv=AppleTVConfig(**raw.get("appletv", {})),
        bridge=BridgeConfig(**raw.get("bridge", {})),
    )
