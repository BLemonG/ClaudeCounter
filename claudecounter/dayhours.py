from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

from .config import CONFIG_DIRECTORY

ACTIVE_HOURS_PATH = CONFIG_DIRECTORY / "dayhours"
MINUTES_PER_DAY = 24 * 60
WHOLE_DAY: Tuple[int, int] = (0, MINUTES_PER_DAY)


def clock(minutes: int) -> str:
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def normalized(hours: Optional[Sequence[int]]) -> Tuple[int, int]:
    if hours is None:
        return WHOLE_DAY
    try:
        opens, shuts = int(hours[0]), int(hours[1])
    except (TypeError, ValueError, IndexError):
        return WHOLE_DAY
    if not 0 <= opens < shuts <= MINUTES_PER_DAY:
        return WHOLE_DAY
    return opens, shuts


def covers_whole_day(hours: Optional[Sequence[int]]) -> bool:
    return normalized(hours) == WHOLE_DAY


def spelled(hours: Optional[Sequence[int]]) -> str:
    opens, shuts = normalized(hours)
    return "%s-%s" % (clock(opens), clock(shuts))


def minutes_from_clock(text: str) -> Optional[int]:
    pieces = text.strip().split(":")
    if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
        return None
    minutes = int(pieces[0]) * 60 + int(pieces[1])
    if not 0 <= minutes <= MINUTES_PER_DAY:
        return None
    return minutes


def hours_from_text(text: str) -> Optional[Tuple[int, int]]:
    pieces = text.replace("–", "-").split("-")
    if len(pieces) != 2:
        return None
    opens = minutes_from_clock(pieces[0])
    shuts = minutes_from_clock(pieces[1])
    if opens is None or shuts is None or opens >= shuts:
        return None
    return opens, shuts


def parsed(text: str) -> Tuple[int, int]:
    found = hours_from_text(text)
    return WHOLE_DAY if found is None else found


def load_active_hours(path: Path = ACTIVE_HOURS_PATH) -> Tuple[int, int]:
    try:
        return parsed(path.read_text())
    except OSError:
        return WHOLE_DAY


def save_active_hours(
    hours: Optional[Sequence[int]], path: Path = ACTIVE_HOURS_PATH
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spelled(hours) + "\n")
    return path
