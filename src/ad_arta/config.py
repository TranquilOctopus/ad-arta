"""Load settings from a TOML file."""

from __future__ import annotations

import codecs
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
    off_delay: float = 0.0
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
    data = config_path.read_bytes()
    # Windows editors/PowerShell may save with a UTF-8 BOM or as UTF-16.
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = data.decode("utf-16")
    else:
        text = data.decode("utf-8-sig")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(
            f"{config_path}: invalid TOML: {e}\n"
            "Check the file is valid TOML (start from a copy of config.example.toml)."
        ) from e

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
