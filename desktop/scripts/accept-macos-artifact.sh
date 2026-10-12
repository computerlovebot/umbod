#!/bin/bash
set -euo pipefail
# No checkout, compiler or externally installed Python is used here.
KIT="$(cd "$(dirname "$0")/.." && pwd)"
DMG="${1:?DMG required}"
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/umbod-test-acceptance.XXXXXX")"
MOUNT="$ROOT/volume"
APP="$ROOT/Applications/Umbod.app"
cleanup() {
    if mount | grep -Fq " on $MOUNT "; then hdiutil detach "$MOUNT" || true; fi
    rm -rf "$ROOT"
}
trap cleanup EXIT
shasum -a 256 "$DMG"
hdiutil verify "$DMG"
hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT" "$DMG"
mkdir -p "$ROOT/Applications"
ditto "$MOUNT/Umbod.app" "$APP"
hdiutil detach "$MOUNT"
codesign --verify --deep --strict "$APP"
PYTHON="$APP/Contents/Resources/python/bin/python3"
cd "$ROOT"
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV CONDA_PREFIX DYLD_LIBRARY_PATH DYLD_FRAMEWORK_PATH
"$PYTHON" -I -B "$KIT/scripts/audit-macos-bundle.py" "$APP"
"$PYTHON" -I -B "$KIT/scripts/verify-python-bundle.py"
"$APP/Contents/MacOS/umbod-desktop" --help > /dev/null
UMBOD_TEST_APP="$APP" UMBOD_TEST_RESOURCES="$KIT" "$KIT/UmbodTests"
codesign --verify --deep --strict "$APP"
printf 'PASS: artifact-only backend and bundle acceptance\n'
