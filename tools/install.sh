#!/bin/bash
set -euo pipefail

LABEL="local.claudecounter.daemon"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIRECTORY="$HOME/Library/LaunchAgents"
AGENT_PLIST="$AGENT_DIRECTORY/$LABEL.plist"
LOG_DIRECTORY="$HOME/Library/Logs/ClaudeCounter"
CONFIG="$HOME/Library/Application Support/ClaudeCounter/config.json"
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

"$PYTHON" "$PROJECT/tools/session_hook.py" register

echo "installed $AGENT_PLIST"
echo "logs: $LOG_DIRECTORY/claudecounter.log"
echo "status: launchctl print gui/$UID/$LABEL | head -20"
