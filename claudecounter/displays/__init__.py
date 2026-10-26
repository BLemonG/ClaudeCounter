from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class Device:
    kind: str
    settings: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "settings": dict(self.settings)}

    @staticmethod
    def from_dict(payload: dict) -> "Device":
        settings = payload.get("settings")
        return Device(
            kind=str(payload["kind"]),
            settings=dict(settings) if isinstance(settings, dict) else {},
        )


@dataclass(frozen=True)
class Candidate:
    kind: str
    name: str
    how: str
    settings: Dict[str, object]

    def spoken(self) -> str:
        return f"{self.name}  ({self.how})"
