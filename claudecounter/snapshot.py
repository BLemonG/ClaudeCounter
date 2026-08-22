from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UsageSnapshot:
    session_pct: float
    session_resets_at: Optional[str]
    weekly_pct: float
    weekly_resets_at: Optional[str]
    fetched_at: str
    stale: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_pct": self.session_pct,
            "session_resets_at": self.session_resets_at,
            "weekly_pct": self.weekly_pct,
            "weekly_resets_at": self.weekly_resets_at,
            "fetched_at": self.fetched_at,
            "stale": self.stale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UsageSnapshot":
        return cls(
            session_pct=float(data.get("session_pct", 0.0)),
            session_resets_at=data.get("session_resets_at"),
            weekly_pct=float(data.get("weekly_pct", 0.0)),
            weekly_resets_at=data.get("weekly_resets_at"),
            fetched_at=data.get("fetched_at") or utc_now_iso(),
            stale=bool(data.get("stale", False)),
        )

    def marked_stale(self) -> "UsageSnapshot":
        if self.stale:
            return self
        return UsageSnapshot(
            session_pct=self.session_pct,
            session_resets_at=self.session_resets_at,
            weekly_pct=self.weekly_pct,
            weekly_resets_at=self.weekly_resets_at,
            fetched_at=self.fetched_at,
            stale=True,
        )
