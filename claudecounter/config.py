from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_DIRECTORY = Path.home() / "Library" / "Application Support" / "ClaudeCounter"
CONFIG_PATH = CONFIG_DIRECTORY / "config.json"

DEFAULT_RFCOMM_CHANNEL = 1


@dataclass(frozen=True)
class DeviceConfig:
    mac: str
    channel: int = DEFAULT_RFCOMM_CHANNEL

    def to_dict(self) -> dict:
        return {"mac": self.mac, "channel": self.channel}

    @staticmethod
    def from_dict(payload: dict) -> "DeviceConfig":
        return DeviceConfig(
            mac=str(payload["mac"]),
            channel=int(payload.get("channel", DEFAULT_RFCOMM_CHANNEL)),
        )


DECLINED_DISPLAY = {"display": False}


def stored_setup() -> Optional[dict]:
    if not CONFIG_PATH.exists():
        return None
    try:
        payload = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def setup_was_done() -> bool:
    payload = stored_setup()
    if payload is None:
        return False
    return "mac" in payload or payload.get("display") is False


def display_was_declined() -> bool:
    payload = stored_setup()
    return payload is not None and "mac" not in payload and payload.get("display") is False


def save_declined_display() -> Path:
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(DECLINED_DISPLAY, indent=2) + "\n")
    return CONFIG_PATH


def load_config() -> Optional[DeviceConfig]:
    if not CONFIG_PATH.exists():
        return None
    try:
        return DeviceConfig.from_dict(json.loads(CONFIG_PATH.read_text()))
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def save_config(config: DeviceConfig) -> Path:
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config.to_dict(), indent=2) + "\n")
    return CONFIG_PATH
