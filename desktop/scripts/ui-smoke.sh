#!/bin/bash
set -euo pipefail
APP="${1:-dist/Umbod.app}"
test -x "$APP/Contents/MacOS/Umbod"
test -x "$APP/Contents/MacOS/umbod-desktop"
test -x "$APP/Contents/Resources/python/bin/python3"
env -i PATH=/usr/bin:/bin "$APP/Contents/Resources/python/bin/python3" -I -B "$(dirname "$0")/verify-python-bundle.py"
/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist"
