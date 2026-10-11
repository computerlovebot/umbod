#!/usr/bin/env python3
"""Run precompiled XCUITests against the exact installed artifact on disposable CI."""

import argparse
import json
import os
import plistlib
import runpy
import subprocess
import tempfile
import uuid
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("app", type=Path)
parser.add_argument("kit", type=Path)
parser.add_argument("evidence", type=Path)
parser.add_argument(
    "--local-fixture",
    action="store_true",
    help="Copy and re-sign the app with a disposable bundle identity",
)
args = parser.parse_args()
if not args.local_fixture and (
    os.environ.get("GITHUB_ACTIONS") != "true"
    or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
):
    raise SystemExit(
        "Release-identity UI tests require a disposable GitHub-hosted Mac; use --local-fixture locally"
    )
app, kit, evidence = (value.resolve() for value in [args.app, args.kit, args.evidence])
# Keep the temporary copy alive for the entire xcodebuild invocation.
local_copy = (
    tempfile.TemporaryDirectory(prefix="umbod-test-ui-app-")
    if args.local_fixture
    else None
)
if local_copy:
    copy = Path(local_copy.name) / "Umbod UI Fixture.app"
    subprocess.run(["/usr/bin/ditto", str(app), str(copy)], check=True)
    app = copy
    info = app / "Contents/Info.plist"
    metadata = plistlib.loads(info.read_bytes())
    metadata["CFBundleIdentifier"] += ".fixture." + uuid.uuid4().hex
    info.write_bytes(plistlib.dumps(metadata))
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", str(app)], check=True
    )
subprocess.run(
    ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True
)
evidence.mkdir(parents=True, exist_ok=True)
products = kit / "ui-tests"
plans = [
    path for path in products.glob("*.xctestrun") if path.name != "configured.xctestrun"
]
if len(plans) != 1:
    raise SystemExit("Expected exactly one precompiled UI test plan")
plan = plistlib.loads(plans[0].read_bytes())
target = plan["ConnectorJourney"]
# The XCTest runner's Foundation temporaryDirectory lives in its app container.
# Create fixture data in the real user's temporary root, recognized by the app's
# deliberately strict FixtureVault guard, without weakening that guard.
data_directory = tempfile.TemporaryDirectory(prefix="umbod-test-ui-data-")
root = Path(data_directory.name).resolve()
directories = {name: root / ("umbod-test-" + name) for name in ("stdio", "oauth")}
Fixture = runpy.run_path(str(kit / "scripts/ui_fixture.py"))["Fixture"]
fixture = Fixture(root, app, kit, directories)
target["EnvironmentVariables"].update(
    {
        "UMBOD_UI_DATA_DIR": str(directories["stdio"]),
        "UMBOD_UI_OAUTH_DATA_DIR": str(directories["oauth"]),
        "UMBOD_UI_FIXTURE_ORIGIN": fixture.origin,
        "UMBOD_UI_FIXTURE_CAPABILITY": fixture.capability,
        "UMBOD_UI_OAUTH_ENDPOINT": fixture.endpoint,
        "UMBOD_UI_CA": str(fixture.cert),
        "UMBOD_UI_APP": str(app),
        "UMBOD_UI_FIXTURE": str(kit / "scripts/fixture_stdio.py"),
        "UMBOD_UI_AGENT": str(kit / "scripts/fixture_agent.py"),
    }
)
target["TestTimeoutsEnabled"] = True
target["MaximumTestExecutionTimeAllowance"] = 180
target["UserAttachmentLifetime"] = "keepAlways"
configured = products / "configured.xctestrun"
configured.write_bytes(plistlib.dumps(plan))
result = evidence / "connector-journey.xcresult"
try:
    subprocess.run(
        [
            "/usr/bin/xcodebuild",
            "test-without-building",
            "-xctestrun",
            str(configured),
            "-destination",
            "platform=macOS,arch=arm64",
            "-parallel-testing-enabled",
            "NO",
            "-resultBundlePath",
            str(result),
        ],
        check=True,
    )
finally:
    fixture.close()
    (evidence / "fixture-requests.json").write_text(
        json.dumps(fixture.requests, indent=2)
    )
    (evidence / "oauth-fixture-audit.json").write_text(
        json.dumps(fixture.audit, indent=2)
    )
summary = subprocess.check_output(
    [
        "/usr/bin/xcrun",
        "xcresulttool",
        "get",
        "test-results",
        "summary",
        "--path",
        str(result),
    ]
)
(evidence / "summary.json").write_bytes(summary)
report = json.loads(summary)
if (
    report.get("passedTests") != 2
    or report.get("failedTests") != 0
    or report.get("skippedTests") != 0
):
    raise SystemExit(
        "Expected two passing UI journeys with no failures or skipped tests"
    )
assert (
    fixture.audit["browser_visits"] >= 1
    and fixture.audit["exchanges"] >= 1
    and fixture.audit["refreshes"] >= 1
    and fixture.audit["calls"] >= 2
), "Browser, PKCE exchange, refresh and authenticated calls must all occur"
print(
    "PASS: packaged local and browser OAuth UI journeys, agent calls, refresh, edit and relaunch"
)

subprocess.run(
    ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True
)
if local_copy:
    local_copy.cleanup()

data_directory.cleanup()
