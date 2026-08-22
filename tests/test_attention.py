from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudecounter import attention

FAILURES = []

HOOK = Path(__file__).resolve().parent.parent / "tools" / "waiting_hook.py"


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def markers_appear_and_disappear() -> None:
    print("markers")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace)
        check(attention.a_session_is_waiting(directory) is False,
              "an empty directory means nothing is waiting")
        attention.mark_waiting("session-a", directory)
        check(attention.a_session_is_waiting(directory) is True,
              "a marked session is reported as waiting")
        attention.mark_waiting("session-b", directory)
        check(attention.waiting_sessions(directory) == ["session-a", "session-b"],
              "two waiting sessions are both listed")
        attention.clear_waiting("session-a", directory)
        check(attention.waiting_sessions(directory) == ["session-b"],
              "clearing one session leaves the other waiting")
        attention.clear_waiting("session-b", directory)
        check(attention.a_session_is_waiting(directory) is False,
              "clearing the last session stops the breathing")
        attention.clear_waiting("never-existed", directory)
        check(True, "clearing an unknown session is not an error")


def a_missing_directory_is_not_an_error() -> None:
    print("missing directory")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace) / "not-created-yet"
        check(attention.waiting_sessions(directory) == [], "an absent directory lists nothing")
        check(attention.a_session_is_waiting(directory) is False,
              "an absent directory means nothing is waiting")
        attention.mark_waiting("session-a", directory)
        check(attention.a_session_is_waiting(directory) is True,
              "marking creates the directory on the way")


def a_crashed_session_stops_breathing_eventually() -> None:
    print("stale markers")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace)
        path = attention.mark_waiting("crashed", directory)
        later = time.time() + attention.MARKER_MAX_AGE_SECONDS + 1.0
        check(attention.a_session_is_waiting(directory, now=later) is False,
              "a marker older than the maximum age no longer counts")
        check(path.exists() is False, "and the stale marker is cleaned up")

        attention.mark_waiting("alive", directory)
        just_inside = time.time() + attention.MARKER_MAX_AGE_SECONDS - 1.0
        check(attention.a_session_is_waiting(directory, now=just_inside) is True,
              "a marker just inside the maximum age still counts")


def session_ids_never_escape_the_directory() -> None:
    print("session id handling")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace)
        for hostile in ("../../etc/passwd", "..", ".", "/etc/passwd", "a/../../b"):
            attention.mark_waiting(hostile, directory)
            check(
                attention.marker_path(hostile, directory).resolve().parent
                == directory.resolve(),
                f"the session id {hostile!r} cannot escape the marker directory",
            )
        check(
            all(entry.is_file() for entry in directory.iterdir()),
            "every marker is a plain file inside the directory",
        )
        attention.mark_waiting("", directory)
        check("unnamed" in [entry.name for entry in directory.iterdir()],
              "an empty session id still gets a marker")


def run_hook(payload, directory: Path) -> int:
    environment = dict(os.environ, HOME=str(directory))
    finished = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload) if isinstance(payload, dict) else payload,
        capture_output=True,
        text=True,
        env=environment,
    )
    return finished.returncode


def markers_for(directory: Path):
    root = directory / "Library" / "Application Support" / "ClaudeCounter" / "waiting"
    return sorted(entry.name for entry in root.iterdir()) if root.is_dir() else []


def the_hook_translates_claude_code_events() -> None:
    print("hook events")
    with tempfile.TemporaryDirectory() as workspace:
        home = Path(workspace)
        check(run_hook({"session_id": "s1", "hook_event_name": "Stop"}, home) == 0,
              "the hook exits zero after Stop")
        check(markers_for(home) == ["s1"], "Stop marks the session as waiting")

        run_hook({"session_id": "s1", "hook_event_name": "UserPromptSubmit"}, home)
        check(markers_for(home) == [], "UserPromptSubmit clears the marker")

        run_hook({"session_id": "s1", "hook_event_name": "Notification"}, home)
        check(markers_for(home) == ["s1"], "a Notification marks the session as waiting")

        run_hook({"session_id": "s1", "hook_event_name": "SessionEnd"}, home)
        check(markers_for(home) == [], "SessionEnd clears the marker")

        run_hook({"session_id": "s2", "hook_event_name": "Stop"}, home)
        run_hook({"session_id": "s3", "hook_event_name": "Stop"}, home)
        check(markers_for(home) == ["s2", "s3"], "two sessions can wait at the same time")
        run_hook({"session_id": "s2", "hook_event_name": "UserPromptSubmit"}, home)
        check(markers_for(home) == ["s3"],
              "answering one session leaves the other one breathing")


def the_hook_survives_anything_on_stdin() -> None:
    print("hook robustness")
    with tempfile.TemporaryDirectory() as workspace:
        home = Path(workspace)
        for payload in ("", "not json at all", "[]", "null", '{"hook_event_name": "Stop"}',
                        '{"session_id": "s1"}', '{"session_id": null, "hook_event_name": "Stop"}'):
            check(run_hook(payload, home) == 0,
                  f"the hook exits zero for {payload!r} and never blocks a session")
        check(markers_for(home) == ["unknown-session"],
              "an event without a session id still records one marker, not a crash")


def main() -> int:
    markers_appear_and_disappear()
    a_missing_directory_is_not_an_error()
    a_crashed_session_stops_breathing_eventually()
    session_ids_never_escape_the_directory()
    the_hook_translates_claude_code_events()
    the_hook_survives_anything_on_stdin()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
