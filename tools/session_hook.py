from __future__ import annotations

import json
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOK_EVENT = "SessionStart"
STATUS_LINE_KEY = "statusLine"


def hook_command() -> str:
    return str((Path(__file__).resolve().parent / "ensure_running.sh"))


def status_line_command() -> str:
    return f"{sys.executable} {Path(__file__).resolve().parent / 'statusline.py'}"


def load_settings() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    return json.loads(SETTINGS_PATH.read_text())


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def groups_of(settings: dict) -> list:
    return settings.get("hooks", {}).get(HOOK_EVENT, [])


def is_registered(settings: dict, command: str) -> bool:
    return any(
        entry.get("command") == command
        for group in groups_of(settings)
        for entry in group.get("hooks", [])
    )


def owns_status_line(settings: dict) -> bool:
    existing = settings.get(STATUS_LINE_KEY)
    if not isinstance(existing, dict):
        return False
    return "statusline.py" in str(existing.get("command", ""))


def register() -> str:
    command = hook_command()
    settings = load_settings()
    messages = []

    if is_registered(settings, command):
        messages.append("session hook already registered")
    else:
        settings.setdefault("hooks", {}).setdefault(HOOK_EVENT, []).append(
            {"hooks": [{"type": "command", "command": command}]}
        )
        messages.append("session hook registered")

    if STATUS_LINE_KEY in settings and not owns_status_line(settings):
        messages.append(
            "a different statusLine is already configured, leaving it alone; "
            "without it the daemon falls back to the usage endpoint"
        )
    else:
        settings[STATUS_LINE_KEY] = {
            "type": "command",
            "command": status_line_command(),
        }
        messages.append("statusLine registered")

    save_settings(settings)
    return f"{'; '.join(messages)} ({SETTINGS_PATH})"


def unregister() -> str:
    command = hook_command()
    settings = load_settings()
    if not is_registered(settings, command) and not owns_status_line(settings):
        return "nothing of ours was registered"
    remaining = []
    for group in groups_of(settings):
        kept = [entry for entry in group.get("hooks", []) if entry.get("command") != command]
        if kept:
            remaining.append({**group, "hooks": kept})
    if remaining:
        settings["hooks"][HOOK_EVENT] = remaining
    else:
        settings["hooks"].pop(HOOK_EVENT, None)
        if not settings["hooks"]:
            settings.pop("hooks", None)
    if owns_status_line(settings):
        settings.pop(STATUS_LINE_KEY, None)
    save_settings(settings)
    return f"session hook and statusLine removed from {SETTINGS_PATH}"


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "register":
        print(register())
    elif action == "unregister":
        print(unregister())
    else:
        print("usage: session_hook.py register|unregister", file=sys.stderr)
        raise SystemExit(2)
