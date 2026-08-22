from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .snapshot import UsageSnapshot, utc_now_iso

CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_ROOT_KEY = "claudeAiOauth"

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
REQUEST_TIMEOUT_SECONDS = 10.0
KEYCHAIN_TIMEOUT_SECONDS = 10.0

LOCAL_USAGE_PATH = (
    Path.home() / "Library" / "Application Support" / "ClaudeCounter" / "usage.json"
)
LOCAL_WRITTEN_AT_KEY = "written_at"
LOCAL_PERCENT_KEY = "used_percentage"
LOCAL_RESETS_AT_KEY = "resets_at"

SESSION_FIELD = "five_hour"
WEEKLY_FIELD = "seven_day"
UTILIZATION_KEY = "utilization"
RESETS_AT_KEY = "resets_at"
RATE_LIMIT_STATUS = 429
RETRY_AFTER_HEADER = "retry-after"
FALLBACK_RETRY_AFTER_SECONDS = 900.0


class UsageError(RuntimeError):
    pass


class MissingCredentials(UsageError):
    pass


class ExpiredCredentials(UsageError):
    pass


class EndpointUnavailable(UsageError):
    pass


class RateLimited(UsageError):
    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UnexpectedSchema(UsageError):
    pass


def credentials_from_file() -> Optional[Dict[str, Any]]:
    if not CREDENTIALS_FILE.is_file():
        return None
    try:
        payload = json.loads(CREDENTIALS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    section = payload.get(CREDENTIALS_ROOT_KEY)
    return section if isinstance(section, dict) else None


def credentials_from_keychain() -> Optional[Dict[str, Any]]:
    try:
        found = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if found.returncode != 0 or not found.stdout.strip():
        return None
    try:
        payload = json.loads(found.stdout)
    except json.JSONDecodeError:
        return None
    section = payload.get(CREDENTIALS_ROOT_KEY)
    return section if isinstance(section, dict) else None


def load_credentials() -> Dict[str, Any]:
    for loader in (credentials_from_file, credentials_from_keychain):
        credentials = loader()
        if credentials and credentials.get("accessToken"):
            return credentials
    raise MissingCredentials(
        "no Claude Code credentials found, "
        f"looked in {CREDENTIALS_FILE} and the {KEYCHAIN_SERVICE} keychain item"
    )


def expiry_of(credentials: Dict[str, Any]) -> Optional[datetime]:
    milliseconds = credentials.get("expiresAt")
    if not isinstance(milliseconds, (int, float)):
        return None
    return datetime.fromtimestamp(milliseconds / 1000.0, timezone.utc)


def access_token(credentials: Dict[str, Any]) -> str:
    expires_at = expiry_of(credentials)
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise ExpiredCredentials(
            f"the Claude Code access token expired at {expires_at.isoformat()}, "
            "sign in again to refresh it"
        )
    token = credentials.get("accessToken")
    if not isinstance(token, str) or not token:
        raise MissingCredentials("the stored credentials carry no access token")
    return token


def retry_after_seconds(headers: Any) -> float:
    raw = headers.get(RETRY_AFTER_HEADER) if headers is not None else None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return FALLBACK_RETRY_AFTER_SECONDS
    return seconds if seconds > 0 else FALLBACK_RETRY_AFTER_SECONDS


def fetch_usage(token: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA_HEADER,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as failure:
        if failure.code in (401, 403):
            raise ExpiredCredentials(
                f"the usage endpoint rejected the token with HTTP {failure.code}, "
                "sign in again to refresh it"
            ) from None
        if failure.code == RATE_LIMIT_STATUS:
            retry_after = retry_after_seconds(failure.headers)
            raise RateLimited(
                f"the usage endpoint is rate limited, not asking again "
                f"for {int(retry_after)}s",
                retry_after,
            ) from None
        raise EndpointUnavailable(
            f"the usage endpoint answered with HTTP {failure.code}"
        ) from None
    except urllib.error.URLError as failure:
        raise EndpointUnavailable(f"could not reach the usage endpoint: {failure.reason}") from None
    except TimeoutError:
        raise EndpointUnavailable(
            f"the usage endpoint did not answer within {REQUEST_TIMEOUT_SECONDS}s"
        ) from None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise UnexpectedSchema("the usage endpoint did not answer with JSON") from None
    if not isinstance(payload, dict):
        raise UnexpectedSchema("the usage endpoint did not answer with a JSON object")
    return payload


def window_of(payload: Dict[str, Any], field: str) -> Dict[str, Any]:
    window = payload.get(field)
    if not isinstance(window, dict):
        raise UnexpectedSchema(f"the usage response carries no {field!r} object")
    return window


def utilization_of(window: Dict[str, Any], field: str) -> float:
    value = window.get(UTILIZATION_KEY)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise UnexpectedSchema(f"{field}.{UTILIZATION_KEY} is not a number")
    return float(value)


def resets_at_of(window: Dict[str, Any]) -> Optional[str]:
    value = window.get(RESETS_AT_KEY)
    return value if isinstance(value, str) and value else None


def snapshot_from_payload(payload: Dict[str, Any]) -> UsageSnapshot:
    session_window = window_of(payload, SESSION_FIELD)
    weekly_window = window_of(payload, WEEKLY_FIELD)
    return UsageSnapshot(
        session_pct=utilization_of(session_window, SESSION_FIELD),
        session_resets_at=resets_at_of(session_window),
        weekly_pct=utilization_of(weekly_window, WEEKLY_FIELD),
        weekly_resets_at=resets_at_of(weekly_window),
        fetched_at=utc_now_iso(),
        stale=False,
    )


def local_window_of(payload: Dict[str, Any], field: str) -> Optional[Dict[str, Any]]:
    window = payload.get(field)
    if not isinstance(window, dict):
        return None
    if not isinstance(window.get(LOCAL_PERCENT_KEY), (int, float)):
        return None
    return window


def has_rolled_over(window: Dict[str, Any], now: datetime) -> bool:
    resets_at = window.get(LOCAL_RESETS_AT_KEY)
    if not isinstance(resets_at, str):
        return True
    try:
        moment = datetime.fromisoformat(resets_at)
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= now


def read_local_usage() -> Optional[UsageSnapshot]:
    try:
        payload = json.loads(LOCAL_USAGE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    session_window = local_window_of(payload, SESSION_FIELD)
    weekly_window = local_window_of(payload, WEEKLY_FIELD)
    if session_window is None or weekly_window is None:
        return None
    written_at = payload.get(LOCAL_WRITTEN_AT_KEY)
    now = datetime.now(timezone.utc)
    return UsageSnapshot(
        session_pct=float(session_window[LOCAL_PERCENT_KEY]),
        session_resets_at=session_window.get(LOCAL_RESETS_AT_KEY),
        weekly_pct=float(weekly_window[LOCAL_PERCENT_KEY]),
        weekly_resets_at=weekly_window.get(LOCAL_RESETS_AT_KEY),
        fetched_at=written_at if isinstance(written_at, str) else utc_now_iso(),
        stale=has_rolled_over(session_window, now),
    )


def read_raw_usage() -> Dict[str, Any]:
    return fetch_usage(access_token(load_credentials()))


def read_usage() -> UsageSnapshot:
    local = read_local_usage()
    if local is not None and not local.stale:
        return local
    try:
        return snapshot_from_payload(read_raw_usage())
    except UsageError:
        if local is not None:
            return local
        raise
