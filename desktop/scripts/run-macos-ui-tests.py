#!/usr/bin/env python3
"""Run precompiled XCUITests against the exact installed artifact on disposable CI."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("app", type=Path)
parser.add_argument("kit", type=Path)
parser.add_argument("evidence", type=Path)
parser.add_argument("--local-fixture", action="store_true", help="Copy and re-sign the app with a disposable bundle identity")
args = parser.parse_args()
if not args.local_fixture and (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"):
    raise SystemExit("Release-identity UI tests require a disposable GitHub-hosted Mac; use --local-fixture locally")
app, kit, evidence = (value.resolve() for value in [args.app, args.kit, args.evidence])
# Keep the temporary copy alive for the entire xcodebuild invocation.
local_copy = tempfile.TemporaryDirectory(prefix="umbod-test-ui-app-") if args.local_fixture else None
if local_copy:
    copy = Path(local_copy.name) / "Umbod UI Fixture.app"
    subprocess.run(["/usr/bin/ditto", str(app), str(copy)], check=True)
    app = copy
    info = app / "Contents/Info.plist"
    metadata = plistlib.loads(info.read_bytes())
    metadata["CFBundleIdentifier"] += ".fixture." + uuid.uuid4().hex
    info.write_bytes(plistlib.dumps(metadata))
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)], check=True)
subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
evidence.mkdir(parents=True, exist_ok=True)
products = kit / "ui-tests"
plans = [path for path in products.glob("*.xctestrun") if path.name != "configured.xctestrun"]
if len(plans) != 1:
    raise SystemExit("Expected exactly one precompiled UI test plan")
plan = plistlib.loads(plans[0].read_bytes())
target = plan["ConnectorJourney"]
# The XCTest runner's Foundation temporaryDirectory lives in its app container.
# Create fixture data in the real user's temporary root, recognized by the app's
# deliberately strict FixtureVault guard, without weakening that guard.
data_directory = tempfile.TemporaryDirectory(prefix="umbod-test-ui-data-")
target["EnvironmentVariables"].update({
    "UMBOD_UI_DATA_DIR": str(Path(data_directory.name).resolve()),
    "UMBOD_UI_APP": str(app),
    "UMBOD_UI_FIXTURE": str(kit / "scripts/fixture_stdio.py"),
    "UMBOD_UI_AGENT": str(kit / "scripts/fixture_agent.py"),
})
target["TestTimeoutsEnabled"] = True
target["MaximumTestExecutionTimeAllowance"] = 180
target["UserAttachmentLifetime"] = "keepAlways"
configured = products / "configured.xctestrun"
configured.write_bytes(plistlib.dumps(plan))
result = evidence / "connector-journey.xcresult"
subprocess.run([
    "/usr/bin/xcodebuild", "test-without-building", "-xctestrun", str(configured),
    "-destination", "platform=macOS,arch=arm64", "-parallel-testing-enabled", "NO",
    "-resultBundlePath", str(result),
], check=True)
summary = subprocess.check_output([
    "/usr/bin/xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(result),
])
(evidence / "summary.json").write_bytes(summary)
report = json.loads(summary)
if report.get("passedTests") != 1 or report.get("failedTests") != 0 or report.get("skippedTests") != 0:
    raise SystemExit("Expected one passing UI journey with no failures or skipped tests")
print("PASS: packaged UI add → discover → enable → agent call → edit → relaunch")

subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
if local_copy:
    local_copy.cleanup()

data_directory.cleanup()
