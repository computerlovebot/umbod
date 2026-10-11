# Umbod Desktop

The native SwiftUI app (Apple Silicon, macOS 14+) uses the shared Python REST/MCP backend through a desktop host in `python/`. WPF (Windows 10/11 x64) continues to use the Rust gateway. Desktop is a single-user, local-first application with tool permissions shared across connected agent clients. macOS bundles its Python interpreter and dependencies; running the app requires neither Docker nor a separately installed Python. It does not require a Kubernetes deployment.

Verified desktop releases are available from https://umbod.ai/download/. Local builds and the manual release workflow currently support **unsigned prereleases only**: macOS is ad-hoc signed and not notarized; Windows is unsigned. Do not disable OS security protections to run a build.

## Build and test

Run from the monorepo root unless a command explicitly changes directory. Build prerequisites: uv, Python 3.11+, Swift 6 and Apple developer tools on macOS; stable Rust (including rustfmt and Clippy), .NET 8 SDK and PowerShell 7 on Windows. uv installs the pinned CPython 3.14.3 build runtime. No command below installs or launches the production app.

```sh
cd desktop
bash scripts/verify.sh          # Python tests, dev bundle, Swift contracts, native smoke
bash scripts/build.sh           # dist/Umbod Dev.app, ad-hoc signed
bash scripts/package.sh         # dist/Umbod-<VERSION>-arm64.dmg
```

The Swift tests are an executable assertion harness, not `swift test`. Tests use temporary directories and an explicitly selected fixture credential store, and require local socket access. Routine Mac tests never access the user’s Keychain. Real app profiles continue to require Keychain, with no plaintext fallback. Do not run them against installed app data. `scripts/verify.sh` runs the Mac checks. Optional `scripts/native-smoke.py` requires a built app and launches only that app with temporary data; it never launches `/Applications/Umbod.app`.

Windows (from `desktop/` in PowerShell):

```powershell
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
cargo test --locked
dotnet run --project windows/Umbod.Core.Tests -c Release -- --gateway "$PWD/target/debug/umbod-gateway.exe"
python scripts/test_windows_package.py
./scripts/package-windows.ps1 -Channel release
```

The ZIP is self-contained; extract the entire archive before running `Umbod.Windows.exe`. Its `--smoke-test` mode constructs the WPF window without starting a gateway or accessing application data. Cross-publishing WPF on macOS proves compilation only; native Windows CI builds the Windows Rust gateway, runs Core integration and the packaged WPF smoke test. Local stdio connectors on Windows must use an executable such as `node.exe`, with explicit arguments; `.cmd`/`.bat` wrappers are not supported.

Repository policy and website checks:

```sh
python3 -m unittest discover -s desktop/tests -v
node --test website/tests/*.test.mjs
cd website && bun run build
```

## Use and lifecycle

Add local executable or remote Streamable HTTP connectors, rediscover their tools, then explicitly enable tools. New tools start disabled. Permission changes apply to subsequent calls from every connected client. Settings → MCP provides bridge configuration. Credentials remain in macOS Keychain or Windows Credential Manager; there is no plaintext fallback.

On macOS, first launch imports existing `config.json` with a resumable journal and preserves the source and a `config.before-python.json` backup. Existing Keychain entries are retained. Import failures remain visible and retry on reopening/restarting; restore missing credentials or executables first. The saved MCP port and existing agent token hashes remain valid. Shared-backend tool names can differ, so clients should refresh their tool catalogs. The old `umbod-gateway` command remains a Python launcher for existing bridge configurations.

Closing the UI leaves the background gateway running. Settings can stop or restart it. Development and release profiles have separate data and vault namespaces (`app.umbod.desktop.dev` and `app.umbod.desktop`). Builds do not migrate, reset, or install app data. Release apps check the published desktop manifest on launch and at most once daily while open. Settings provides a manual update check, an automatic-check preference, release notes, and a guided installer download/quit flow. Users can defer or skip a version; manual checks show skipped versions again. Development builds default to manual checks, and isolated smoke tests never check online. Updates are not installed automatically, and there is no login supervisor.

OAuth supports native public clients with loopback callbacks, discovery, PKCE and refresh. Real OAuth providers are not certified. Legacy standalone SSE upstreams, resources, prompts, sampling, and tool argument-level policies are unsupported. Desktop does not claim the Kubernetes edition's organization identity or group administration capabilities.

## Code and release index

- [`python/`](python/README.md): macOS host, transport adapters, Keychain, migration and tests; reuses `umbod/api` and `packages/umbod-sdk`.
- `backend/src/`: Windows Rust gateway, profiles, platform adapters, client setup and OAuth; `backend/tests/`: integration tests.
- `native/`: SwiftUI app and Swift contract/lifecycle tests; `UmbodCore/DesktopUpdate.swift` validates update metadata and `Umbod/UpdatesView.swift` owns update preferences and the install guidance.
- `windows/`: shared .NET Core contracts, Core tests, and WPF app; `Umbod.Core/DesktopUpdate.cs` validates update metadata and `Umbod.Windows/UpdatesView.cs` provides update checks and install guidance.
- `scripts/`: local builds, packaging, isolated fixtures, and release policy/metadata.
- `VERSION`: independent desktop version; keep Cargo.toml and the gateway entry in Cargo.lock synchronized. Bundle, package and .NET versions derive from it.
- [Release procedure](docs/RELEASING.md), [manifest application](docs/APPLY-MANIFEST.md), and [import provenance and audit](docs/PROVENANCE.md).

The [upstream Windows run](https://github.com/kasperjunge/umbod-desktop/actions/runs/37907078176) is historical source evidence supplied for this import. It is **not** a CI result for this target repository or these integration changes.

Release packaging collects dependency inventories and notices through `scripts/dependency-notices.py`; pinned supplemental sources are documented in `licenses/README.md`. `scripts/verify-python-bundle.py` rejects editable installs and imports outside the bundled interpreter before signing and again after installation. `scripts/audit-macos-bundle.py` verifies ARM64 slices, the macOS 14 deployment floor, required resources, executable permissions, internal symlinks and relocatable native dependencies. `Resources/build-metadata.json` records source and toolchain inputs. `scripts/prepare-macos-acceptance.sh` packages a precompiled test harness and fixtures; the separate `macos-acceptance` job runs `scripts/accept-macos-artifact.sh` on current macOS ARM64 with no checkout, using the DMG’s interpreter and the unchanged release identity. This required job also runs in the manual release workflow before publication. Local UI tests retain disposable bundle identities to protect user preferences. `scripts/install-smoke.py` installs the Mac DMG into disposable storage and verifies the packaged connector/agent flow, native window lifecycle, and signature integrity before and after execution. It never uses the login Keychain.
