from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claudecounter import attention

SESSION_ID_KEY = "session_id"
EVENT_KEY = "hook_event_name"
MARKING_EVENTS = ("Stop", "Notification")
CLEARING_EVENTS = ("UserPromptSubmit", "SessionStart", "SessionEnd")
FALLBACK_SESSION_ID = "unknown-session"


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def session_of(payload: dict) -> str:
    value = payload.get(SESSION_ID_KEY)
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value)
    return FALLBACK_SESSION_ID


def apply(payload: dict) -> str:
    event = str(payload.get(EVENT_KEY, ""))
    session = session_of(payload)
    if event in MARKING_EVENTS:
        attention.mark_waiting(session)
        return "waiting"
    if event in CLEARING_EVENTS:
        attention.clear_waiting(session)
        return "busy"
    return "ignored"


def main() -> int:
    try:
        apply(read_payload())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
