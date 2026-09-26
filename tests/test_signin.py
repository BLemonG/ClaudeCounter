from __future__ import annotations

import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
from pathlib import Path

from claudecounter import signin

FAILURES = []


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def fake_claude(recorded_arguments: Path) -> str:
    folder = Path(tempfile.mkdtemp(prefix="claudecounter-signin-"))
    executable = folder / "claude"
    executable.write_text(f'#!/bin/sh\necho "$@" > "{recorded_arguments}"\n')
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return str(executable)


def with_fakes(executable, expiries):
    original_executable = signin.claude_executable
    original_expiry = signin.stored_expiry
    readings = iter(expiries)
    signin.claude_executable = lambda: executable
    signin.stored_expiry = lambda: next(readings)
    try:
        return signin.ask_claude_code_to_renew()
    finally:
        signin.claude_executable = original_executable
        signin.stored_expiry = original_expiry


def a_moved_expiry_counts_as_renewed() -> None:
    print("renewed sign-in")
    recorded = Path(tempfile.mkdtemp()) / "arguments"
    now = datetime.now(timezone.utc)
    renewed = with_fakes(fake_claude(recorded), [now - timedelta(hours=1), now + timedelta(hours=8)])
    check(renewed == now + timedelta(hours=8), "the new expiry is reported")
    arguments = recorded.read_text().split()
    check(arguments[0] == "-p" and arguments[-1] == signin.MINI_REQUEST_PROMPT,
          "one short print-mode request is sent")
    check("haiku" in arguments, "the smallest model answers it")
    check("--strict-mcp-config" in arguments and "--no-session-persistence" in arguments,
          "no MCP servers are started and no transcript is written")
    check("--disable-slash-commands" in arguments, "no skills are loaded")


def an_unchanged_expiry_counts_as_not_renewed() -> None:
    print("unchanged sign-in")
    recorded = Path(tempfile.mkdtemp()) / "arguments"
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    check(with_fakes(fake_claude(recorded), [past, past]) is None,
          "an expiry in the past is no renewal")
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    check(with_fakes(fake_claude(recorded), [future, future]) is None,
          "an expiry that did not move is no renewal")
    check(with_fakes(fake_claude(recorded), [past, None]) is None,
          "unreadable credentials are no renewal")


def a_missing_claude_is_not_an_error() -> None:
    print("missing claude")
    check(with_fakes(None, [None, None]) is None, "without claude nothing is run and nothing breaks")
    check(with_fakes("/nonexistent/claude", [None, None]) is None,
          "a claude that cannot be started is no renewal")


def main() -> int:
    a_moved_expiry_counts_as_renewed()
    an_unchanged_expiry_counts_as_not_renewed()
    a_missing_claude_is_not_an_error()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
