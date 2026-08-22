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


ELSEWHERE = "com.apple.Safari"
AT_THE_CHAT = "com.anthropic.claudefordesktop"


def breathing(directory, front=ELSEWHERE, idle=5.0, now=None) -> bool:
    return attention.a_session_is_waiting(
        directory, now=now, frontmost=lambda: front, idle_seconds=lambda: idle
    )


def markers_appear_and_disappear() -> None:
    print("markers")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace)
        check(breathing(directory) is False,
              "an empty directory means nothing is waiting")
        attention.mark_waiting("session-a", directory)
        check(breathing(directory) is True,
              "a marked session is reported as waiting")
        attention.mark_waiting("session-b", directory)
        check(attention.waiting_sessions(directory) == ["session-a", "session-b"],
              "two waiting sessions are both listed")
        attention.clear_waiting("session-a", directory)
        check(attention.waiting_sessions(directory) == ["session-b"],
              "clearing one session leaves the other waiting")
        attention.clear_waiting("session-b", directory)
        check(breathing(directory) is False,
              "clearing the last session stops the breathing")
        attention.clear_waiting("never-existed", directory)
        check(True, "clearing an unknown session is not an error")


def a_missing_directory_is_not_an_error() -> None:
    print("missing directory")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace) / "not-created-yet"
        check(attention.waiting_sessions(directory) == [], "an absent directory lists nothing")
        check(breathing(directory) is False,
              "an absent directory means nothing is waiting")
        attention.mark_waiting("session-a", directory)
        check(breathing(directory) is True,
              "marking creates the directory on the way")


def a_crashed_session_stops_breathing_eventually() -> None:
    print("stale markers")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace)
        path = attention.mark_waiting("crashed", directory)
        later = time.time() + attention.BREATH_MAX_SECONDS + 1.0
        check(breathing(directory, now=later) is False,
              f"nothing breathes longer than {attention.BREATH_MAX_SECONDS}s, even unseen")
        check(path.exists() is False, "and the expired marker is cleaned up")

        attention.mark_waiting("alive", directory)
        just_inside = time.time() + attention.BREATH_MAX_SECONDS - 1.0
        check(breathing(directory, now=just_inside) is True,
              "a marker just inside the cap still breathes")


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


def the_breathing_stops_once_the_user_looks_at_the_chat() -> None:
    print("stopping when the chat is looked at")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace) / "waiting"
        attention.remember_owner("s1", AT_THE_CHAT, directory)
        attention.mark_waiting("s1", directory)
        check(attention.marker_path("s1", directory).read_text() == AT_THE_CHAT,
              "the marker records which app the session belongs to")

        check(breathing(directory, front=ELSEWHERE, idle=5.0) is True,
              "while another app is in front the counter keeps breathing")
        check(breathing(directory, front=AT_THE_CHAT, idle=600.0) is True,
              "the chat being in front is not enough, nobody is at the keyboard")
        check(breathing(directory, front=AT_THE_CHAT, idle=5.0) is False,
              "the chat in front plus someone at the keyboard stops the breathing")
        check(attention.waiting_sessions(directory) == [],
              "and the marker is gone, so switching away does not restart it")
        check(breathing(directory, front=ELSEWHERE, idle=5.0) is False,
              "leaving the chat again does not bring the breathing back")


def only_the_session_that_was_seen_stops_breathing() -> None:
    print("several sessions in different apps")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace) / "waiting"
        attention.mark_waiting("desktop-session", directory, owner=AT_THE_CHAT)
        attention.mark_waiting("terminal-session", directory, owner="com.apple.Terminal")

        check(breathing(directory, front=AT_THE_CHAT, idle=5.0) is True,
              "looking at one chat leaves the other session breathing")
        check(attention.waiting_sessions(directory) == ["terminal-session"],
              "only the session that was actually looked at is cleared")
        check(breathing(directory, front="com.apple.Terminal", idle=5.0) is False,
              "looking at the second one too stops the breathing")


def an_unknown_owner_keeps_breathing() -> None:
    print("unknown owner")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace) / "waiting"
        attention.mark_waiting("no-owner", directory, owner="")
        check(breathing(directory, front=AT_THE_CHAT, idle=5.0) is True,
              "a marker without a known app is never cleared by looking somewhere")
        check(breathing(directory, front=None, idle=5.0) is True,
              "an unreadable frontmost app leaves the breathing alone")
        check(breathing(directory, front=AT_THE_CHAT, idle=None) is True,
              "an unreadable idle time leaves the breathing alone")
        check(attention.waiting_sessions(directory) == ["no-owner"],
              "and the marker survives all three")


def owners_outlive_a_turn_but_not_forever() -> None:
    print("owner bookkeeping")
    with tempfile.TemporaryDirectory() as workspace:
        directory = Path(workspace) / "waiting"
        attention.remember_owner("s1", "com.apple.Terminal", directory)
        attention.mark_waiting("s1", directory)
        attention.clear_waiting("s1", directory)
        attention.mark_waiting("s1", directory)
        check(attention.marker_path("s1", directory).read_text() == "com.apple.Terminal",
              "the remembered app survives a turn without being asked again")

        attention.remember_owner("s1", None, directory)
        check(attention.owner_of("s1", directory) == "com.apple.Terminal",
              "an unreadable frontmost app does not wipe what we already knew")

        attention.prune_owners(directory, now=time.time() + attention.OWNER_MAX_AGE_SECONDS + 1)
        check(attention.owner_of("s1", directory) == "",
              "owners of long dead sessions are pruned")

        attention.remember_owner("s2", "com.apple.Terminal", directory)
        attention.mark_waiting("s2", directory)
        attention.forget_session("s2", directory)
        check("s2" not in attention.waiting_sessions(directory)
              and attention.owner_of("s2", directory) == "",
              "ending a session drops both its marker and its remembered app")


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


def owners_for(directory: Path):
    root = directory / "Library" / "Application Support" / "ClaudeCounter" / "owners"
    return sorted(entry.name for entry in root.iterdir()) if root.is_dir() else []


def refresh_pending(directory: Path) -> bool:
    root = directory / "Library" / "Application Support" / "ClaudeCounter"
    return (root / attention.REFRESH_FILE_NAME).exists()


def the_hook_translates_claude_code_events() -> None:
    print("hook events")
    with tempfile.TemporaryDirectory() as workspace:
        home = Path(workspace)
        check(run_hook({"session_id": "s1", "hook_event_name": "Stop"}, home) == 0,
              "the hook exits zero after Stop")
        check(markers_for(home) == [],
              "a finished answer alone does not breathe, otherwise every reply would")
        check(refresh_pending(home) is True,
              "but a finished answer does ask for fresh usage numbers")

        check(run_hook({"session_id": "s1", "hook_event_name": "Notification"}, home) == 0,
              "the hook exits zero after Notification")
        check(markers_for(home) == ["s1"],
              "a notification is what breathes, the same event macOS notifies on")

        run_hook({"session_id": "s1", "hook_event_name": "UserPromptSubmit"}, home)
        check(markers_for(home) == [], "UserPromptSubmit clears the marker")

        run_hook({"session_id": "s1", "hook_event_name": "Notification"}, home)
        run_hook({"session_id": "s1", "hook_event_name": "Stop"}, home)
        check(markers_for(home) == [],
              "a permission granted mid turn stops breathing when the turn ends")

        run_hook({"session_id": "s2", "hook_event_name": "Notification"}, home)
        run_hook({"session_id": "s3", "hook_event_name": "Notification"}, home)
        check(markers_for(home) == ["s2", "s3"], "two sessions can wait at the same time")
        run_hook({"session_id": "s2", "hook_event_name": "UserPromptSubmit"}, home)
        check(markers_for(home) == ["s3"],
              "answering one session leaves the other one breathing")
        run_hook({"session_id": "s3", "hook_event_name": "SessionEnd"}, home)
        check(markers_for(home) == [] and "s3" not in owners_for(home),
              "SessionEnd drops the marker and the remembered app together")


def the_hook_survives_anything_on_stdin() -> None:
    print("hook robustness")
    with tempfile.TemporaryDirectory() as workspace:
        home = Path(workspace)
        for payload in ("", "not json at all", "[]", "null", '{"hook_event_name": "Stop"}',
                        '{"session_id": "s1"}', '{"session_id": "s1", "hook_event_name": "Nope"}'):
            check(run_hook(payload, home) == 0,
                  f"the hook exits zero for {payload!r} and never blocks a session")
        check(markers_for(home) == [],
              "none of that garbage produced a marker or a crash")
        check(run_hook('{"session_id": null, "hook_event_name": "Notification"}', home) == 0,
              "a notification without a session id is still handled")
        check(markers_for(home) == ["unknown-session"],
              "and it records one marker under a fallback name")


def main() -> int:
    markers_appear_and_disappear()
    a_missing_directory_is_not_an_error()
    a_crashed_session_stops_breathing_eventually()
    session_ids_never_escape_the_directory()
    the_breathing_stops_once_the_user_looks_at_the_chat()
    only_the_session_that_was_seen_stops_breathing()
    an_unknown_owner_keeps_breathing()
    owners_outlive_a_turn_but_not_forever()
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
