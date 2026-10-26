from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .displays import Device

CONFIG_DIRECTORY = Path.home() / "Library" / "Application Support" / "ClaudeCounter"
CONFIG_PATH = CONFIG_DIRECTORY / "config.json"

DEFAULT_RFCOMM_CHANNEL = 1
DEFAULT_KIND = "timebox-evo"
DECLINED_DISPLAY = {"display": False}


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


def stored_setup() -> Optional[dict]:
    if not CONFIG_PATH.exists():
        return None
    try:
        payload = json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def write_setup(payload: dict) -> Path:
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    return CONFIG_PATH


def load_device() -> Optional[Device]:
    payload = stored_setup()
    if payload is None:
        return None
    if "kind" in payload:
        try:
            return Device.from_dict(payload)
        except (KeyError, TypeError, ValueError):
            return None
    if "mac" in payload:
        try:
            older = DeviceConfig.from_dict(payload)
        except (KeyError, TypeError, ValueError):
            return None
        return Device(kind=DEFAULT_KIND, settings=older.to_dict())
    return None


def save_device(device: Device) -> Path:
    return write_setup(device.to_dict())


def setup_was_done() -> bool:
    payload = stored_setup()
    if payload is None:
        return False
    return "kind" in payload or "mac" in payload or payload.get("display") is False


def display_was_declined() -> bool:
    return stored_setup() is not None and load_device() is None and setup_was_done()


def save_declined_display() -> Path:
    return write_setup(dict(DECLINED_DISPLAY))


def load_config() -> Optional[DeviceConfig]:
    device = load_device()
    if device is None or device.kind != DEFAULT_KIND:
        return None
    try:
        return DeviceConfig.from_dict(dict(device.settings))
    except (KeyError, TypeError, ValueError):
        return None


def save_config(config: DeviceConfig) -> Path:
    return save_device(Device(kind=DEFAULT_KIND, settings=config.to_dict()))
