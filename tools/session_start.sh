#!/bin/bash
set -euo pipefail

LABEL="local.claudecounter.sessionstart"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIRECTORY="$HOME/Library/Logs/ClaudeCounter"
PYTHON="$(command -v python3)"
WANTED="${1:-05:00}"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true

if [ "$WANTED" = "off" ]; then
    rm -f "$AGENT_PLIST"
    echo "morning session start removed"
    exit 0
fi

if ! [[ "$WANTED" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    echo "usage: $0 [HH:MM|off], for example $0 05:00" >&2
    exit 1
fi

mkdir -p "$(dirname "$AGENT_PLIST")" "$LOG_DIRECTORY"

sed -e "s|__LABEL__|$LABEL|g" \
    -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__WORKDIR__|$PROJECT|g" \
    -e "s|__LOGDIR__|$LOG_DIRECTORY|g" \
    -e "s|__PATH__|/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin|g" \
    -e "s|__AT__|$WANTED|g" \
    -e "s|__HOUR__|$((10#${WANTED%%:*}))|g" \
    -e "s|__MINUTE__|$((10#${WANTED##*:}))|g" \
    "$PROJECT/tools/launchagent.sessionstart.plist.template" > "$AGENT_PLIST"

plutil -lint "$AGENT_PLIST" >/dev/null
launchctl bootstrap "gui/$UID" "$AGENT_PLIST"

echo "installed $AGENT_PLIST, opening the 5h window Mon-Fri at $WANTED"
echo "log: $LOG_DIRECTORY/claudecounter.log"
