from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
START_EVENT = "SessionStart"
WAITING_EVENTS = ("Stop", "Notification", "UserPromptSubmit", "SessionStart", "SessionEnd")
STATUS_LINE_KEY = "statusLine"


def here() -> Path:
    return Path(__file__).resolve().parent


def start_command() -> str:
    return str(here() / "ensure_running.sh")


def waiting_command() -> str:
    return f"{sys.executable} {here() / 'waiting_hook.py'}"


def status_line_command() -> str:
    return f"{sys.executable} {here() / 'statusline.py'}"


def our_commands() -> List[Tuple[str, str]]:
    pairs = [(START_EVENT, start_command())]
    pairs += [(event, waiting_command()) for event in WAITING_EVENTS]
    return pairs


def load_settings() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    return json.loads(SETTINGS_PATH.read_text())


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def groups_of(settings: dict, event: str) -> list:
    return settings.get("hooks", {}).get(event, [])


def is_registered(settings: dict, event: str, command: str) -> bool:
    return any(
        entry.get("command") == command
        for group in groups_of(settings, event)
        for entry in group.get("hooks", [])
    )


def add_hook(settings: dict, event: str, command: str) -> bool:
    if is_registered(settings, event, command):
        return False
    settings.setdefault("hooks", {}).setdefault(event, []).append(
        {"hooks": [{"type": "command", "command": command}]}
    )
    return True


def remove_hook(settings: dict, event: str, command: str) -> bool:
    if not is_registered(settings, event, command):
        return False
    remaining = []
    for group in groups_of(settings, event):
        kept = [entry for entry in group.get("hooks", []) if entry.get("command") != command]
        if kept:
            remaining.append({**group, "hooks": kept})
    if remaining:
        settings["hooks"][event] = remaining
    else:
        settings["hooks"].pop(event, None)
        if not settings["hooks"]:
            settings.pop("hooks", None)
    return True


def owns_status_line(settings: dict) -> bool:
    existing = settings.get(STATUS_LINE_KEY)
    if not isinstance(existing, dict):
        return False
    return "statusline.py" in str(existing.get("command", ""))


def register() -> str:
    settings = load_settings()
    added: Dict[str, int] = {}
    for event, command in our_commands():
        if add_hook(settings, event, command):
            added[event] = added.get(event, 0) + 1

    messages = []
    if added:
        messages.append("registered hooks on " + ", ".join(sorted(added)))
    else:
        messages.append("hooks already registered")

    if STATUS_LINE_KEY in settings and not owns_status_line(settings):
        messages.append(
            "a different statusLine is already configured, leaving it alone; "
            "without it the daemon falls back to the usage endpoint"
        )
    else:
        settings[STATUS_LINE_KEY] = {"type": "command", "command": status_line_command()}
        messages.append("statusLine registered")

    save_settings(settings)
    return f"{'; '.join(messages)} ({SETTINGS_PATH})"


def unregister() -> str:
    settings = load_settings()
    removed = [event for event, command in our_commands() if remove_hook(settings, event, command)]
    dropped_status_line = owns_status_line(settings)
    if dropped_status_line:
        settings.pop(STATUS_LINE_KEY, None)
    if not removed and not dropped_status_line:
        return "nothing of ours was registered"
    save_settings(settings)
    return f"removed our hooks and statusLine from {SETTINGS_PATH}"


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "register":
        print(register())
    elif action == "unregister":
        print(unregister())
    else:
        print("usage: session_hook.py register|unregister", file=sys.stderr)
        raise SystemExit(2)
