# Umbod Desktop

The macOS-only native SwiftUI app (Apple Silicon, macOS 14+) uses the shared Python REST/MCP backend through a desktop host in `python/`. Desktop is a single-user, local-first application with tool permissions shared across connected agent clients. macOS bundles its Python interpreter and dependencies; running the app requires neither Docker nor a separately installed Python. It does not require a Kubernetes deployment.

Verified desktop releases are available from https://umbod.ai/download/. Local builds and the manual release workflow currently support **unsigned prereleases only**: macOS is ad-hoc signed and not notarized. Do not disable OS security protections to run a build.

## Build and test

Run from the monorepo root unless a command explicitly changes directory. Build prerequisites: uv, Python 3.11+, Swift 6 and Apple developer tools on macOS. Packaging downloads a pinned CPython 3.14.3 runtime and verifies its SHA-256. No command below installs or launches the production app.

```sh
cd desktop
bash scripts/verify.sh          # Python tests, dev bundle, Swift contracts, native smoke
bash scripts/build.sh           # dist/Umbod Dev.app, ad-hoc signed
bash scripts/package.sh         # dist/Umbod-<VERSION>-arm64.dmg
```

The Swift tests are an executable assertion harness, not `swift test`. Tests use temporary directories and an explicitly selected fixture credential store, and require local socket access. Routine Mac tests never access the user’s Keychain. Real app profiles continue to require Keychain, with no plaintext fallback. Do not run them against installed app data. `scripts/verify.sh` runs the Mac checks. Optional `scripts/native-smoke.py` requires a built app and launches only that app with temporary data; it never launches `/Applications/Umbod.app`.

Repository policy and website checks:

```sh
python3 -m unittest discover -s desktop/tests -v
node --test website/tests/*.test.mjs
cd website && bun run build
```

## Use and lifecycle

Add local executable or remote Streamable HTTP connectors, rediscover their tools, then explicitly enable tools. New tools start disabled. Permission changes apply to subsequent calls from every connected client. Settings → MCP provides bridge configuration. Credentials remain in macOS Keychain; there is no plaintext fallback.

On macOS, first launch imports existing `config.json` with a resumable journal and preserves the source and a `config.before-python.json` backup. Existing Keychain entries are retained. Import failures remain visible and retry on reopening/restarting; restore missing credentials or executables first. The saved MCP port and existing agent token hashes remain valid. Shared-backend tool names can differ, so clients should refresh their tool catalogs. The old `umbod-gateway` command remains a Python launcher for existing bridge configurations.

Closing the UI leaves the background gateway running. Settings can stop or restart it. Development and release profiles have separate data and vault namespaces (`app.umbod.desktop.dev` and `app.umbod.desktop`). Builds do not migrate, reset, or install app data. Release apps check the published desktop manifest on launch and at most once daily while open. Settings provides a manual update check, an automatic-check preference, release notes, and a guided installer download/quit flow. Users can defer or skip a version; manual checks show skipped versions again. Development builds default to manual checks, and isolated smoke tests never check online. Updates are not installed automatically, and there is no login supervisor.

OAuth supports native public clients with loopback callbacks, discovery, PKCE and refresh. Real OAuth providers are not certified. Legacy standalone SSE upstreams, resources, prompts, sampling, and tool argument-level policies are unsupported. Desktop does not claim the Kubernetes edition's organization identity or group administration capabilities.

Older installed versions that require a Windows asset in update metadata cannot read new macOS-only manifests. Download the first macOS-only release manually from the website; its updater accepts both historical and macOS-only manifests. Existing published releases are not changed.

## Code and release index

- [`python/`](python/README.md): macOS host, transport adapters, Keychain, migration and tests; reuses `umbod/api` and `packages/umbod-sdk`.
- `native/`: SwiftUI app and Swift contract/lifecycle tests; `UmbodCore/ConnectorEditor.swift` owns the actual editor submission and retry state; `UITests/` contains the XCUITest project for packaged-app user journeys; `UmbodCore/DesktopUpdate.swift` validates update metadata and `Umbod/UpdatesView.swift` owns update preferences and the install guidance.
- `scripts/`: local builds, packaging, isolated fixtures, and release policy/metadata.
- `VERSION`: independent desktop version; the single source for bundle and package versions.
- [Release procedure](docs/RELEASING.md), [manifest application](docs/APPLY-MANIFEST.md), and [import provenance and audit](docs/PROVENANCE.md).

Release packaging collects dependency inventories and notices through `scripts/dependency-notices.py`; pinned supplemental sources are documented in `licenses/README.md`. `scripts/verify-python-bundle.py` rejects editable installs and imports outside the bundled interpreter before signing and again after installation. `scripts/audit-macos-bundle.py` verifies ARM64 slices, the macOS 14 deployment floor, required resources, executable permissions, internal symlinks and relocatable native dependencies. `Resources/build-metadata.json` records source and toolchain inputs. `scripts/prepare-macos-acceptance.sh` packages a precompiled test harness and fixtures; the separate `macos-acceptance` job runs `scripts/accept-macos-artifact.sh` on current macOS ARM64 with no checkout, using the DMG’s interpreter and the unchanged release identity. This required job also runs in the manual release workflow before publication. Local UI tests retain disposable bundle identities to protect user preferences. `scripts/install-smoke.py` installs the Mac DMG into disposable storage and verifies the packaged connector/agent flow, native window lifecycle, and signature integrity before and after execution. It never uses the login Keychain.

The acceptance kit also includes a precompiled XCUITest runner. `scripts/run-macos-ui-tests.py` runs it with `xcodebuild test-without-building` on the disposable hosted Mac. It clicks Add connector, saves a local fixture, discovers and enables its echo tool, calls it through the packaged agent bridge, edits the connector, and verifies persistence after relaunch. A second journey adds a remote HTTPS MCP fixture, opens a real browser for synthetic consent, completes discovery/registration and the PKCE callback, enables and calls a tool, refreshes the token, and verifies authenticated calls after relaunch. The fixture delays catalog responses beyond five seconds to catch accidental HTTP client timeouts. `scripts/ui_fixture.py` owns the local OAuth server and runs the packaged agent outside the sandboxed XCTest runner; its control endpoints require an ephemeral capability. Its temporary certificate is trusted only by the test app process, with no Keychain or system trust changes. No API shortcut creates or enables connectors. This tests the standards-based sign-in flow with an isolated synthetic provider. The required gate rejects failed or skipped journeys and preserves `.xcresult` diagnostics and screenshots. The runner uses temporary data and fixture credentials, never the login Keychain. Local UI testing uses `--local-fixture` to copy and re-sign the app with a unique bundle identity; release-identity execution remains restricted to disposable CI. The app is still built with SwiftPM, and the separate test project does not build or modify it.

To run the same click-through journey locally without touching installed apps or profiles:

```sh
bash desktop/scripts/prepare-macos-acceptance.sh /tmp/umbod-ui-kit
python3 desktop/scripts/run-macos-ui-tests.py "desktop/dist/Umbod Dev.app" /tmp/umbod-ui-kit /tmp/umbod-ui-evidence --local-fixture
```

Build the dev bundle first. Use a fresh kit directory per build and a new evidence directory per run. Xcode UI testing may request macOS automation/accessibility access on first use; do not bypass system controls. The CI gate still tests the unchanged release artifact.
