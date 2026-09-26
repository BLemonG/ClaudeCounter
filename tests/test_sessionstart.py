from __future__ import annotations

import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from pathlib import Path

from claudecounter import sessionstart

FAILURES = []
FIVE = 5 * 60
MONDAY = datetime(2026, 9, 21, 5, 0)


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("claudecounter-sessionstart-test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def scratch_last_opening() -> Path:
    return Path(tempfile.mkdtemp(prefix="claudecounter-sessionstart-")) / "session-opened-on"


def only_working_mornings_are_due() -> None:
    print("when the morning start is due")
    check(sessionstart.reason_to_skip(MONDAY, FIVE, None) is None, "Monday 05:00 is due")
    check(sessionstart.reason_to_skip(MONDAY.replace(day=25, minute=40), FIVE, None) is None,
          "Friday 05:40 still counts as the morning start")
    check(sessionstart.reason_to_skip(MONDAY.replace(day=26), FIVE, None) is not None,
          "Saturday is skipped")
    check(sessionstart.reason_to_skip(MONDAY.replace(day=27), FIVE, None) is not None,
          "Sunday is skipped")
    check(sessionstart.reason_to_skip(MONDAY.replace(hour=4, minute=59), FIVE, None) is not None,
          "a minute early is too early")
    check(sessionstart.reason_to_skip(MONDAY.replace(hour=6, minute=1), FIVE, None) is not None,
          "a Mac that wakes after 06:00 does not open a late window")
    check(sessionstart.reason_to_skip(MONDAY, FIVE, MONDAY.date()) is not None,
          "a second start on the same day is skipped")
    check(sessionstart.reason_to_skip(MONDAY, FIVE, date(2026, 9, 18)) is None,
          "an opening on an earlier day does not block today")


def a_due_morning_sends_one_request() -> None:
    print("sending the morning request")
    sent, refreshes, pauses = [], [], []
    path = scratch_last_opening()

    def send() -> bool:
        sent.append(True)
        return True

    opened = sessionstart.open_the_session(
        quiet_logger(), FIVE, now=MONDAY, send_mini_request=send,
        request_refresh=lambda: refreshes.append(True), pause=pauses.append,
        last_opening_path=path,
    )
    check(opened is True and len(sent) == 1, "one request opens the window")
    check(sessionstart.load_last_opening(path) == MONDAY.date(), "the day is remembered")
    check(refreshes == [True], "the counter is asked to fetch the new window early")

    again = sessionstart.open_the_session(
        quiet_logger(), FIVE, now=MONDAY.replace(minute=10), send_mini_request=send,
        request_refresh=lambda: None, pause=pauses.append, last_opening_path=path,
    )
    check(again is False and len(sent) == 1, "a second run on the same morning sends nothing")


def a_failing_request_is_retried_then_given_up() -> None:
    print("failing morning request")
    sent, pauses = [], []
    path = scratch_last_opening()

    def send() -> bool:
        sent.append(True)
        return len(sent) == 2

    opened = sessionstart.open_the_session(
        quiet_logger(), FIVE, now=MONDAY, send_mini_request=send,
        request_refresh=lambda: None, pause=pauses.append, last_opening_path=path,
    )
    check(opened is True and len(sent) == 2, "a second attempt can still open the window")
    check(len(pauses) == 1, "the attempts are spaced apart")

    sent.clear()
    pauses.clear()
    path = scratch_last_opening()
    opened = sessionstart.open_the_session(
        quiet_logger(), FIVE, now=MONDAY, send_mini_request=lambda: sent.append(True) and False,
        request_refresh=lambda: None, pause=pauses.append, last_opening_path=path,
    )
    check(opened is False and len(sent) == sessionstart.ATTEMPTS, "it gives up after the last attempt")
    check(sessionstart.load_last_opening(path) is None, "a failed morning is not remembered as done")


def a_dry_run_sends_nothing() -> None:
    print("dry run")
    sent = []
    opened = sessionstart.open_the_session(
        quiet_logger(), FIVE, now=MONDAY, send_mini_request=lambda: sent.append(True) or True,
        request_refresh=lambda: None, pause=lambda seconds: None,
        last_opening_path=scratch_last_opening(), dry_run=True,
    )
    check(opened is True and sent == [], "a dry run only reports that it would send")


def main() -> int:
    only_working_mornings_are_due()
    a_due_morning_sends_one_request()
    a_failing_request_is_retried_then_given_up()
    a_dry_run_sends_nothing()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
