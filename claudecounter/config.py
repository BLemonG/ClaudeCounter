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
