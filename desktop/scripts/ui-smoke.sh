#!/bin/bash
set -euo pipefail
APP="${1:-dist/Umbod.app}"
test -x "$APP/Contents/MacOS/Umbod"
test -x "$APP/Contents/MacOS/umbod-desktop"
test -x "$APP/Contents/Resources/python/bin/python3"
env -i PATH=/usr/bin:/bin "$APP/Contents/Resources/python/bin/python3" -I -B -c 'import umbod_desktop, umbod.rest.main, umbod.mcp.public_app'
/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist"
