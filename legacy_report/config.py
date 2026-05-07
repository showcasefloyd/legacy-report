import json
from pathlib import Path

CONFIG_DIR = Path("~/.config/legacy-report").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "comicvine_api_key": "",
    "cache_ttl_hours": 12,
    "db_path": "~/.local/share/legacy-report/collection.db",
}


def get_config() -> dict:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE) as f:
        return {**DEFAULT_CONFIG, **json.load(f)}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_api_key() -> str:
    return get_config().get("comicvine_api_key", "")


def set_api_key(key: str) -> None:
    config = get_config()
    config["comicvine_api_key"] = key
    save_config(config)
