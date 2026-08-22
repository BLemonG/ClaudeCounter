from __future__ import annotations

import re
import subprocess
from typing import Optional

FRONTMOST_COMMAND = ("lsappinfo", "front")
BUNDLE_ID_COMMAND = ("lsappinfo", "info", "-only", "bundleid")
IDLE_COMMAND = ("ioreg", "-c", "IOHIDSystem", "-d", "4")
BUNDLE_ID_PATTERN = re.compile(r'"CFBundleIdentifier"\s*=\s*"([^"]+)"')
IDLE_PATTERN = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')
NANOSECONDS_PER_SECOND = 1_000_000_000.0
COMMAND_TIMEOUT = 2.0
AT_THE_KEYBOARD_WITHIN_SECONDS = 90.0


def run(command) -> Optional[str]:
    try:
        finished = subprocess.run(
            list(command), capture_output=True, text=True, timeout=COMMAND_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0:
        return None
    return finished.stdout


def frontmost_bundle_id() -> Optional[str]:
    handle = run(FRONTMOST_COMMAND)
    if not handle or not handle.strip():
        return None
    described = run(BUNDLE_ID_COMMAND + (handle.strip(),))
    if not described:
        return None
    match = BUNDLE_ID_PATTERN.search(described)
    return match.group(1) if match else None


def seconds_since_input() -> Optional[float]:
    described = run(IDLE_COMMAND)
    if not described:
        return None
    match = IDLE_PATTERN.search(described)
    if not match:
        return None
    return int(match.group(1)) / NANOSECONDS_PER_SECOND


def at_the_keyboard(
    idle: Optional[float], within: float = AT_THE_KEYBOARD_WITHIN_SECONDS
) -> bool:
    return idle is not None and idle <= within
