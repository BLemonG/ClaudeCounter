#!/bin/bash
set -euo pipefail

LABEL="local.claudecounter.daemon"
GUARD_LABEL="local.claudecounter.audioguard"
MENU_LABEL="local.claudecounter.menu"
AGENT_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GUARD_PLIST="$HOME/Library/LaunchAgents/$GUARD_LABEL.plist"
MENU_PLIST="$HOME/Library/LaunchAgents/$MENU_LABEL.plist"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$AGENT_PLIST"

launchctl bootout "gui/$UID/$GUARD_LABEL" 2>/dev/null || true
rm -f "$GUARD_PLIST"

launchctl bootout "gui/$UID/$MENU_LABEL" 2>/dev/null || true
rm -f "$MENU_PLIST"

python3 "$(cd "$(dirname "$0")" && pwd)/session_hook.py" unregister

echo "removed $AGENT_PLIST"
echo "removed $GUARD_PLIST"
echo "removed $MENU_PLIST"
echo "logs kept in $HOME/Library/Logs/ClaudeCounter"
