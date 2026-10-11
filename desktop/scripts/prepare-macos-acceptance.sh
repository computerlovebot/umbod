#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${1:?test kit output directory required}"
if [[ -e "$DEST/ui-tests" ]]; then
    echo "Choose a fresh kit directory; an existing UI test kit must not be mixed with a new build." >&2
    exit 1
fi
mkdir -p "$DEST/scripts" "$DEST/tests/fixtures"
swift build --package-path native --product UmbodTests
cp native/.build/debug/UmbodTests "$DEST/UmbodTests"
cp scripts/{accept-macos-artifact.sh,audit-macos-bundle.py,verify-python-bundle.py,native-smoke.py,fixture_stdio.py,fixture_agent.py,run-macos-ui-tests.py,ui_fixture.py} "$DEST/scripts/"
cp tests/fixtures/update-manifest.json "$DEST/tests/fixtures/"

# Only the test runner is compiled here. XCUITest launches the separately packaged app.
xcodebuild build-for-testing -project native/UITests/ConnectorJourney.xcodeproj \
    -scheme ConnectorJourney -destination 'platform=macOS,arch=arm64' \
    -derivedDataPath "$DEST/ui-build"
mv "$DEST/ui-build/Build/Products" "$DEST/ui-tests"
rm -rf "$DEST/ui-build"
