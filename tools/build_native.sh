#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

BUNDLE="claudecounter/bin/ClaudeCounterBluetooth.app"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS"
cp tools/Info.plist "$BUNDLE/Contents/Info.plist"

swiftc -O -framework IOBluetooth -o "$BUNDLE/Contents/MacOS/bt_probe" tools/bt_probe.swift
swiftc -O -framework CoreAudio -o claudecounter/bin/audio_guard tools/audio_guard.swift

MENU="claudecounter/bin/ClaudeCounterMenu.app"
rm -rf "$MENU"
mkdir -p "$MENU/Contents/MacOS"
cp tools/Info.menubar.plist "$MENU/Contents/Info.plist"
swiftc -O -framework AppKit -framework UserNotifications \
    -o "$MENU/Contents/MacOS/ClaudeCounterMenu" tools/menubar.swift
codesign --force --deep --sign - \
    -r='designated => identifier "local.claudecounter.menu"' "$MENU"
codesign --force --deep --sign - "$BUNDLE"

echo "built $BUNDLE"
echo "built claudecounter/bin/audio_guard"
echo "built $MENU"
