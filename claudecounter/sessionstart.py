from __future__ import annotations

import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from . import attention, dayhours, signin
from .config import CONFIG_DIRECTORY

DEFAULT_OPENING_MINUTES = 5 * 60
LATEST_DELAY_MINUTES = 60
WORKING_DAY_COUNT = 5
ATTEMPTS = 3
PAUSE_BETWEEN_ATTEMPTS_SECONDS = 60.0
LAST_OPENING_PATH = CONFIG_DIRECTORY / "session-opened-on"


def reason_to_skip(now: datetime, opening_minutes: int,
                   last_opened_on: Optional[date]) -> Optional[str]:
    if now.weekday() >= WORKING_DAY_COUNT:
        return "it is the weekend"
    if last_opened_on == now.date():
        return "the session was already opened today"
    minutes_now = now.hour * 60 + now.minute
    if minutes_now < opening_minutes:
        return "it is before %s" % dayhours.clock(opening_minutes)
    latest = opening_minutes + LATEST_DELAY_MINUTES
    if minutes_now > latest:
        return "it is past %s, the morning start was missed" % dayhours.clock(latest)
    return None


def load_last_opening(path: Path = LAST_OPENING_PATH) -> Optional[date]:
    try:
        return date.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None


def save_last_opening(day: date, path: Path = LAST_OPENING_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(day.isoformat() + "\n")


def open_the_session(
    logger: logging.Logger,
    opening_minutes: int = DEFAULT_OPENING_MINUTES,
    now: Optional[datetime] = None,
    send_mini_request: Callable[[], bool] = signin.send_mini_request,
    request_refresh: Callable[[], object] = attention.request_refresh,
    pause: Callable[[float], None] = time.sleep,
    last_opening_path: Path = LAST_OPENING_PATH,
    dry_run: bool = False,
) -> bool:
    moment = now or datetime.now()
    skip = reason_to_skip(moment, opening_minutes, load_last_opening(last_opening_path))
    if skip is not None:
        logger.info("morning session start skipped, %s", skip)
        return False
    if dry_run:
        logger.info("morning session start would send its request now")
        return True
    for attempt in range(1, ATTEMPTS + 1):
        if send_mini_request():
            save_last_opening(moment.date(), last_opening_path)
            try:
                request_refresh()
            except OSError:
                pass
            logger.info("morning session started with a short request (attempt %d)", attempt)
            return True
        if attempt < ATTEMPTS:
            pause(PAUSE_BETWEEN_ATTEMPTS_SECONDS)
    logger.warning("morning session start failed after %d attempt(s)", ATTEMPTS)
    return False
