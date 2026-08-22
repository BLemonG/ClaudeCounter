#!/bin/bash

LABEL="local.claudecounter.daemon"
AGENT_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -f "$AGENT_PLIST" ]; then
    exit 0
fi

if ! launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    launchctl bootstrap "gui/$UID" "$AGENT_PLIST" >/dev/null 2>&1
fi

launchctl kickstart "gui/$UID/$LABEL" >/dev/null 2>&1

exit 0
