from __future__ import annotations

from pathlib import Path
from typing import FrozenSet, Iterable, List, Optional

from .config import CONFIG_DIRECTORY

ACTIVE_DAYS_PATH = CONFIG_DIRECTORY / "weekdays"
EVERY_DAY: FrozenSet[int] = frozenset(range(7))
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WORKING_DAYS: FrozenSet[int] = frozenset(range(5))
MARKS = "01"


def normalized(days: Optional[Iterable[int]]) -> FrozenSet[int]:
    if days is None:
        return EVERY_DAY
    kept = frozenset(int(day) for day in days if 0 <= int(day) <= 6)
    return kept or EVERY_DAY


def counts_every_day(days: Optional[Iterable[int]]) -> bool:
    return normalized(days) == EVERY_DAY


def spelled(days: Optional[Iterable[int]]) -> str:
    chosen = normalized(days)
    return "".join("1" if day in chosen else "0" for day in range(7))


def parsed(text: str) -> FrozenSet[int]:
    cleaned = text.strip()
    if len(cleaned) != 7 or set(cleaned) - set(MARKS):
        return EVERY_DAY
    return normalized(day for day, mark in enumerate(cleaned) if mark == "1")


def named(days: Optional[Iterable[int]]) -> str:
    chosen = normalized(days)
    return ",".join(DAY_NAMES[day] for day in sorted(chosen))


def day_from_name(name: str) -> Optional[int]:
    cleaned = name.strip().lower()[:3]
    if cleaned in DAY_NAMES:
        return DAY_NAMES.index(cleaned)
    return None


def days_from_names(text: str) -> Optional[FrozenSet[int]]:
    wanted: List[int] = []
    for piece in text.replace(" ", ",").split(","):
        if not piece:
            continue
        day = day_from_name(piece)
        if day is None:
            return None
        wanted.append(day)
    if not wanted:
        return None
    return frozenset(wanted)


def load_active_days(path: Path = ACTIVE_DAYS_PATH) -> FrozenSet[int]:
    try:
        return parsed(path.read_text())
    except OSError:
        return EVERY_DAY


def save_active_days(
    days: Optional[Iterable[int]], path: Path = ACTIVE_DAYS_PATH
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spelled(days) + "\n")
    return path
