#!/bin/bash
set -euo pipefail

LABEL="local.claudecounter.daemon"
AGENT_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$AGENT_PLIST"

python3 "$(cd "$(dirname "$0")" && pwd)/session_hook.py" unregister

echo "removed $AGENT_PLIST"
echo "logs kept in $HOME/Library/Logs/ClaudeCounter"
