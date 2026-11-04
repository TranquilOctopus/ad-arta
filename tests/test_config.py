from pathlib import Path

from ad_arta.config import load_config


def test_token_path_is_relative_to_config(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[tv]\nhost = "10.0.0.5"\n[bridge]\noff_delay = 1.5\n')
    cfg = load_config(str(cfg_file))
    assert cfg.tv.host == "10.0.0.5"
    assert cfg.tv.token_file == str(tmp_path / "tv-token.txt")
    assert cfg.bridge.off_delay == 1.5
    assert cfg.appletv.identifier == ""


def test_example_config_loads():
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(str(root / "config.example.toml"))
    assert cfg.tv.mac
