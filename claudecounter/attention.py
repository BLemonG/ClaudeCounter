from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import presence

ATTENTION_DIRECTORY = Path.home() / "Library" / "Application Support" / "ClaudeCounter"
WAITING_DIRECTORY = ATTENTION_DIRECTORY / "waiting"
OWNERS_DIRECTORY_NAME = "owners"
REFRESH_FILE_NAME = "refresh-please"
BREATH_MAX_SECONDS = 15 * 60
OWNER_MAX_AGE_SECONDS = 24 * 60 * 60
SAFE_SESSION_ID = re.compile(r"[^A-Za-z0-9._-]")


def marker_name(session_id: str) -> str:
    cleaned = SAFE_SESSION_ID.sub("-", str(session_id)).strip("-.")
    return cleaned or "unnamed"


def waiting_directory(directory: Optional[Path] = None) -> Path:
    return directory or WAITING_DIRECTORY


def owners_directory(directory: Optional[Path] = None) -> Path:
    return waiting_directory(directory).parent / OWNERS_DIRECTORY_NAME


def refresh_path(directory: Optional[Path] = None) -> Path:
    return waiting_directory(directory).parent / REFRESH_FILE_NAME


def request_refresh(directory: Optional[Path] = None) -> Path:
    return write_text(refresh_path(directory), "")


def refresh_requested(directory: Optional[Path] = None) -> bool:
    return refresh_path(directory).exists()


def consume_refresh(directory: Optional[Path] = None) -> bool:
    try:
        refresh_path(directory).unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def marker_path(session_id: str, directory: Optional[Path] = None) -> Path:
    return waiting_directory(directory) / marker_name(session_id)


def owner_path(session_id: str, directory: Optional[Path] = None) -> Path:
    return owners_directory(directory) / marker_name(session_id)


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, None)
    return path


def read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def remember_owner(
    session_id: str, bundle_id: Optional[str], directory: Optional[Path] = None
) -> Optional[Path]:
    if not bundle_id:
        return None
    return write_text(owner_path(session_id, directory), bundle_id)


def owner_of(session_id: str, directory: Optional[Path] = None) -> str:
    return read_text(owner_path(session_id, directory))


def mark_waiting(
    session_id: str, directory: Optional[Path] = None, owner: Optional[str] = None
) -> Path:
    remembered = owner if owner is not None else owner_of(session_id, directory)
    return write_text(marker_path(session_id, directory), remembered or "")


def clear_waiting(session_id: str, directory: Optional[Path] = None) -> None:
    try:
        marker_path(session_id, directory).unlink()
    except FileNotFoundError:
        pass


def forget_session(session_id: str, directory: Optional[Path] = None) -> None:
    clear_waiting(session_id, directory)
    try:
        owner_path(session_id, directory).unlink()
    except FileNotFoundError:
        pass


def prune_owners(directory: Optional[Path] = None, now: Optional[float] = None) -> None:
    reference = time.time() if now is None else now
    try:
        entries = list(owners_directory(directory).iterdir())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return
    for entry in entries:
        try:
            if reference - entry.stat().st_mtime > OWNER_MAX_AGE_SECONDS:
                entry.unlink()
        except OSError:
            continue


def waiting_markers(
    directory: Optional[Path] = None,
    now: Optional[float] = None,
    maximum_age: float = BREATH_MAX_SECONDS,
) -> List[Tuple[str, str]]:
    reference = time.time() if now is None else now
    try:
        entries = sorted(waiting_directory(directory).iterdir())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []
    fresh = []
    for entry in entries:
        try:
            age = reference - entry.stat().st_mtime
        except OSError:
            continue
        if age <= maximum_age:
            fresh.append((entry.name, read_text(entry)))
        else:
            try:
                entry.unlink()
            except OSError:
                pass
    return fresh


def waiting_sessions(
    directory: Optional[Path] = None,
    now: Optional[float] = None,
    maximum_age: float = BREATH_MAX_SECONDS,
) -> List[str]:
    return [name for name, _ in waiting_markers(directory, now, maximum_age)]


def a_session_is_waiting(
    directory: Optional[Path] = None,
    now: Optional[float] = None,
    maximum_age: float = BREATH_MAX_SECONDS,
    frontmost=presence.frontmost_bundle_id,
    idle_seconds=presence.seconds_since_input,
) -> bool:
    markers = waiting_markers(directory, now, maximum_age)
    if not markers:
        return False
    front = frontmost()
    present = presence.at_the_keyboard(idle_seconds())
    unseen = []
    for session, owner in markers:
        if present and front and owner and owner == front:
            clear_waiting(session, directory)
        else:
            unseen.append(session)
    return bool(unseen)
