#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

BUNDLE="claudecounter/bin/ClaudeCounterBluetooth.app"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS"
cp tools/Info.plist "$BUNDLE/Contents/Info.plist"

swiftc -O -framework IOBluetooth -o "$BUNDLE/Contents/MacOS/bt_probe" tools/bt_probe.swift
codesign --force --deep --sign - "$BUNDLE"

echo "built $BUNDLE"
