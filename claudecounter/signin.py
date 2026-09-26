from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import usage_source

CLAUDE_SEARCH_DIRECTORIES = (
    Path.home() / ".local" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)
CAFFEINATE = Path("/usr/bin/caffeinate")
STAY_AWAKE_SECONDS = 180
MINI_REQUEST_TIMEOUT_SECONDS = 90.0
MINI_REQUEST_PROMPT = "OK"
MINI_REQUEST_ARGUMENTS = (
    "-p",
    "--model", "haiku",
    "--setting-sources", "",
    "--strict-mcp-config",
    "--tools", "",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--system-prompt", "Answer with the single word OK.",
)
MINI_REQUEST_DIRECTORY = Path.home() / "Library" / "Application Support" / "ClaudeCounter" / "renewal"


def claude_executable() -> Optional[str]:
    search = os.pathsep.join(
        [str(directory) for directory in CLAUDE_SEARCH_DIRECTORIES]
        + [os.environ.get("PATH", "")]
    )
    return shutil.which("claude", path=search)


def stored_expiry() -> Optional[datetime]:
    try:
        return usage_source.expiry_of(usage_source.load_credentials())
    except usage_source.UsageError:
        return None


def start_staying_awake() -> Optional[subprocess.Popen]:
    if not CAFFEINATE.exists():
        return None
    try:
        return subprocess.Popen(
            [str(CAFFEINATE), "-i", "-t", str(STAY_AWAKE_SECONDS)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


def send_mini_request() -> bool:
    executable = claude_executable()
    if executable is None:
        return False
    awake = start_staying_awake()
    try:
        MINI_REQUEST_DIRECTORY.mkdir(parents=True, exist_ok=True)
        finished = subprocess.run(
            [executable, *MINI_REQUEST_ARGUMENTS, MINI_REQUEST_PROMPT],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(MINI_REQUEST_DIRECTORY),
            timeout=MINI_REQUEST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        if awake is not None:
            awake.terminate()
    return finished.returncode == 0


def ask_claude_code_to_renew() -> Optional[datetime]:
    before = stored_expiry()
    send_mini_request()
    after = stored_expiry()
    if after is None or after <= datetime.now(timezone.utc):
        return None
    if before is not None and after <= before:
        return None
    return after
