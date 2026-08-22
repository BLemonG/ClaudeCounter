#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

USAGE_PATH = Path.home() / "Library" / "Application Support" / "ClaudeCounter" / "usage.json"
TRACE_PATH = Path.home() / "Library" / "Logs" / "ClaudeCounter" / "statusline.log"
TRACE_KEEP_LINES = 200
RATE_LIMITS_KEY = "rate_limits"
SESSION_KEY = "five_hour"
WEEKLY_KEY = "seven_day"
PERCENT_KEY = "used_percentage"
RESETS_AT_KEY = "resets_at"


def epoch_to_iso(value) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def window_of(limits, key):
    window = limits.get(key)
    if not isinstance(window, dict):
        return None
    percent = window.get(PERCENT_KEY)
    if not isinstance(percent, (int, float)):
        return None
    return {"used_percentage": float(percent), "resets_at": epoch_to_iso(window.get(RESETS_AT_KEY))}


def store(payload) -> dict | None:
    limits = payload.get(RATE_LIMITS_KEY)
    if not isinstance(limits, dict):
        return None
    session = window_of(limits, SESSION_KEY)
    weekly = window_of(limits, WEEKLY_KEY)
    if session is None and weekly is None:
        return None
    record = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        SESSION_KEY: session,
        WEEKLY_KEY: weekly,
    }
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = USAGE_PATH.with_suffix(".json.partial")
    temporary.write_text(json.dumps(record))
    temporary.replace(USAGE_PATH)
    return record


def trace(payload) -> None:
    limits = payload.get(RATE_LIMITS_KEY)
    if isinstance(limits, dict):
        verdict = "rate_limits present: " + ",".join(sorted(limits))
    elif RATE_LIMITS_KEY in payload:
        verdict = f"rate_limits present but not an object: {type(limits).__name__}"
    else:
        verdict = "rate_limits ABSENT"
    entry = "{} | {} | keys: {}\n".format(
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        verdict,
        ",".join(sorted(payload)),
    )
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    previous = []
    if TRACE_PATH.exists():
        previous = TRACE_PATH.read_text().splitlines(keepends=True)[-TRACE_KEEP_LINES:]
    TRACE_PATH.write_text("".join(previous) + entry)


def status_line(payload, record) -> str:
    parts = []
    model = payload.get("model")
    if isinstance(model, dict) and model.get("display_name"):
        parts.append(str(model["display_name"]))
    if record:
        for key, label in ((SESSION_KEY, "5h"), (WEEKLY_KEY, "7d")):
            window = record.get(key)
            if window:
                parts.append(f"{label} {window['used_percentage']:.0f}%")
    context = payload.get("context_window")
    if isinstance(context, dict) and isinstance(context.get("used_percentage"), (int, float)):
        parts.append(f"ctx {context['used_percentage']:.0f}%")
    return "  ".join(parts)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        trace(payload)
    except Exception:
        pass
    try:
        record = store(payload)
    except Exception:
        record = None
    line = status_line(payload, record)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
