import json
import os

CONFIG_DIR = os.path.expanduser("~/Library/Application Support/FileWatcherMac")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "source_dir": "",
    "dest_dir": "",
    "monitoring": False,
    "recursive": True,
    "auto_start": False,
}


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_config():
    ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = dict(DEFAULT_CONFIG)
            merged.update(saved)
            return merged
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def update_config(key, value):
    config = load_config()
    config[key] = value
    save_config(config)
    return config
