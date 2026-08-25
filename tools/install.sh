#!/bin/bash
set -euo pipefail

LABEL="local.claudecounter.daemon"
GUARD_LABEL="local.claudecounter.audioguard"
MENU_LABEL="local.claudecounter.menu"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIRECTORY="$HOME/Library/LaunchAgents"
AGENT_PLIST="$AGENT_DIRECTORY/$LABEL.plist"
GUARD_PLIST="$AGENT_DIRECTORY/$GUARD_LABEL.plist"
MENU_PLIST="$AGENT_DIRECTORY/$MENU_LABEL.plist"
LOG_DIRECTORY="$HOME/Library/Logs/ClaudeCounter"
STATE_DIRECTORY="$HOME/Library/Application Support/ClaudeCounter"
CONFIG="$STATE_DIRECTORY/config.json"
PYTHON="$(command -v python3)"

if [ -z "$PYTHON" ]; then
    echo "python3 not found on PATH" >&2
    exit 1
fi

if ! "$PYTHON" -c "import PIL" 2>/dev/null; then
    echo "Pillow is not installed for $PYTHON, run: $PYTHON -m pip install Pillow" >&2
    exit 1
fi

if [ ! -d "$PROJECT/claudecounter/bin/ClaudeCounterBluetooth.app" ]; then
    echo "bluetooth helper missing, run tools/build_native.sh first" >&2
    exit 1
fi

if [ ! -x "$PROJECT/claudecounter/bin/audio_guard" ]; then
    echo "audio guard missing, run tools/build_native.sh first" >&2
    exit 1
fi

if [ ! -f "$CONFIG" ]; then
    echo "no device configured, run: $PYTHON -m claudecounter configure --mac <ADDRESS>" >&2
    exit 1
fi

mkdir -p "$AGENT_DIRECTORY" "$LOG_DIRECTORY"

sed -e "s|__LABEL__|$LABEL|g" \
    -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__WORKDIR__|$PROJECT|g" \
    -e "s|__LOGDIR__|$LOG_DIRECTORY|g" \
    -e "s|__PATH__|/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin|g" \
    "$PROJECT/tools/launchagent.plist.template" > "$AGENT_PLIST"

plutil -lint "$AGENT_PLIST" >/dev/null

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$AGENT_PLIST"
launchctl kickstart -k "gui/$UID/$LABEL"

DEVICE_ADDRESS="$("$PYTHON" -c 'import json,sys,pathlib; print(json.loads(pathlib.Path(sys.argv[1]).read_text()).get("mac",""))' "$CONFIG")"
DEVICE_NAME="$(system_profiler SPBluetoothDataType 2>/dev/null | awk -v want="$(echo "$DEVICE_ADDRESS" | tr 'A-Z' 'a-z')" '
    /^ {10,14}[^ ].*:$/ { candidate = $0; sub(/^ +/, "", candidate); sub(/:$/, "", candidate) }
    tolower($0) ~ want { print candidate; exit }')"
AUDIO_NAME_FRAGMENT="${CLAUDECOUNTER_AUDIO_NAME:-${DEVICE_NAME:-TimeBox}}"

sed -e "s|__LABEL__|$GUARD_LABEL|g" \
    -e "s|__GUARD__|$PROJECT/claudecounter/bin/audio_guard|g" \
    -e "s|__FRAGMENT__|$AUDIO_NAME_FRAGMENT|g" \
    -e "s|__STATEDIR__|$STATE_DIRECTORY|g" \
    -e "s|__LOGDIR__|$LOG_DIRECTORY|g" \
    "$PROJECT/tools/launchagent.audioguard.plist.template" > "$GUARD_PLIST"

plutil -lint "$GUARD_PLIST" >/dev/null

launchctl bootout "gui/$UID/$GUARD_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$GUARD_PLIST"
launchctl kickstart -k "gui/$UID/$GUARD_LABEL"

sed -e "s|__LABEL__|$MENU_LABEL|g" \
    -e "s|__MENU__|$PROJECT/claudecounter/bin/ClaudeCounterMenu.app/Contents/MacOS/ClaudeCounterMenu|g" \
    -e "s|__LOGDIR__|$LOG_DIRECTORY|g" \
    "$PROJECT/tools/launchagent.menu.plist.template" > "$MENU_PLIST"

plutil -lint "$MENU_PLIST" >/dev/null

launchctl bootout "gui/$UID/$MENU_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$MENU_PLIST"
launchctl kickstart -k "gui/$UID/$MENU_LABEL"

"$PYTHON" "$PROJECT/tools/session_hook.py" register

echo "installed $AGENT_PLIST"
echo "installed $GUARD_PLIST, keeping audio away from \"$AUDIO_NAME_FRAGMENT\""
echo "installed $MENU_PLIST, the menu bar entry starts at login"
echo "logs: $LOG_DIRECTORY/claudecounter.log"
echo "status: launchctl print gui/$UID/$LABEL | head -20"
