"""Configuration and credential storage.

Two locations are involved:

    ~/.ps5rmtctl/config.json   # our saved default host / user (this module)
    ~/.pyremoteplay/.profile.json  # PSN account + per-console registration keys

The profiles file is owned by pyremoteplay. We deliberately do NOT relocate it:
pyremoteplay's ``Profiles.save()`` ignores ``set_default_path()`` and always
writes to ``~/.pyremoteplay``, so overriding only the load path leaves save and
load disagreeing. Instead we just make sure that directory exists (pyremoteplay's
``write_profiles`` does not create it on its own).

Override our config dir with the PS5RMTCTL_HOME environment variable.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Optional

# pyremoteplay's fixed profile location (see pyremoteplay.const.PROFILE_DIR).
PYRP_DIR = pathlib.Path.home() / ".pyremoteplay"

CONFIG_DIR = pathlib.Path(
    os.environ.get("PS5RMTCTL_HOME") or (pathlib.Path.home() / ".ps5rmtctl")
)
CONFIG_PATH = CONFIG_DIR / "config.json"


def ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def init_profiles() -> None:
    """Ensure pyremoteplay's profile directory exists before load/save.

    Must be called before any pyremoteplay call that loads/saves profiles.
    """
    ensure_dir()
    PYRP_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict) -> None:
    ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


def update_config(**kwargs) -> dict:
    config = load_config()
    config.update({k: v for k, v in kwargs.items() if v is not None})
    save_config(config)
    return config


def get_default(key: str) -> Optional[str]:
    return load_config().get(key)
