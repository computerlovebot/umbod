#!/usr/bin/env python3
"""Run precompiled XCUITests against the exact installed artifact on disposable CI."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
    raise SystemExit("Release-identity UI tests require a disposable GitHub-hosted Mac")
app, kit, evidence = map(lambda value: Path(value).resolve(), sys.argv[1:])
evidence.mkdir(parents=True, exist_ok=True)
products = kit / "ui-tests"
plans = list(products.glob("*.xctestrun"))
if len(plans) != 1:
    raise SystemExit("Expected exactly one precompiled UI test plan")
plan = plistlib.loads(plans[0].read_bytes())
target = plan["ConnectorJourney"]
target["EnvironmentVariables"].update({
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
