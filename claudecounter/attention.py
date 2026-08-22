from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import List, Optional

WAITING_DIRECTORY = (
    Path.home() / "Library" / "Application Support" / "ClaudeCounter" / "waiting"
)
MARKER_MAX_AGE_SECONDS = 4 * 60 * 60
SAFE_SESSION_ID = re.compile(r"[^A-Za-z0-9._-]")


def marker_name(session_id: str) -> str:
    cleaned = SAFE_SESSION_ID.sub("-", str(session_id)).strip("-.")
    return cleaned or "unnamed"


def marker_path(session_id: str, directory: Optional[Path] = None) -> Path:
    return (directory or WAITING_DIRECTORY) / marker_name(session_id)


def mark_waiting(session_id: str, directory: Optional[Path] = None) -> Path:
    path = marker_path(session_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, None)
    return path


def clear_waiting(session_id: str, directory: Optional[Path] = None) -> None:
    try:
        marker_path(session_id, directory).unlink()
    except FileNotFoundError:
        pass


def waiting_sessions(
    directory: Optional[Path] = None,
    now: Optional[float] = None,
    maximum_age: float = MARKER_MAX_AGE_SECONDS,
) -> List[str]:
    root = directory or WAITING_DIRECTORY
    reference = time.time() if now is None else now
    try:
        entries = sorted(root.iterdir())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []
    fresh = []
    for entry in entries:
        try:
            age = reference - entry.stat().st_mtime
        except OSError:
            continue
        if age <= maximum_age:
            fresh.append(entry.name)
        else:
            try:
                entry.unlink()
            except OSError:
                pass
    return fresh


def a_session_is_waiting(
    directory: Optional[Path] = None,
    now: Optional[float] = None,
    maximum_age: float = MARKER_MAX_AGE_SECONDS,
) -> bool:
    return bool(waiting_sessions(directory, now, maximum_age))
