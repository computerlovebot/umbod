# Desktop releases

Desktop is versioned independently of chart, images and SDK. Update `desktop/VERSION`, the single source for bundle and package versions. No version is taken from repository-wide `latest`, root release metadata or Kubernetes tags. Tags are exactly `desktop-vX.Y.Z`; GitHub prerelease status, rather than a tag suffix, marks the currently supported channel.

## Current supported path: unsigned prerelease

1. Resolve the source-license and dependency-notice blockers in [provenance](PROVENANCE.md), review the changes, and merge through the normal process. Do not copy historical personal docs or evidence.
2. Configure the GitHub `desktop-release` environment with required reviewers and a deployment branch rule permitting only `main`. The workflow also validates repository, ref, event, version, rights attestation, and exact confirmation. No signing secret is required for unsigned builds. No credentials belong in website code or manifests.
3. Run native desktop CI on the reviewed source. PR/push CI only uploads artifacts and has read-only permissions. macOS builds use an Apple Silicon runner and Swift 6. The Mac artifact-only acceptance job must also pass: it uses the exact DMG, no checkout or compiler, and an unchanged release app launched through LaunchServices on a fresh hosted runner. Automated click-through UI tests are currently removed; verify connector creation/editing, tool enablement, browser sign-in, refresh, and persistence manually.
4. From `main`, explicitly dispatch **Desktop manual prerelease** with version `X.Y.Z`, mode `unsigned-prerelease`, rights confirmation enabled, and confirmation text `release desktop-vX.Y.Z unsigned-prerelease`. The workflow rebuilds/tests the dispatch SHA. It creates a new desktop tag, an explicitly UNSIGNED GitHub prerelease, versioned assets, release notes, SHA256SUMS and desktop-downloads.json. It never promotes repository-wide latest or overwrites existing tags/releases/assets.
5. Download the `website-manifest-update` artifact and follow [APPLY-MANIFEST.md](APPLY-MANIFEST.md). This is a PR-ready file tree; publication does not automatically edit or deploy the website.

Only the publish job has contents:write, after guard and macOS build and artifact acceptance. It uses the workflow token only for GitHub release operations. This implementation was not dispatched or published during integration. The workflow must be merged to the default branch before it can be manually dispatched.

Metadata generation rejects unexpected files, directories and symbolic links in the release staging directory. Publication explicitly uploads only the versioned macOS DMG, SHA256SUMS, desktop-downloads.json and RELEASE_NOTES.md.

If a tag was created but upload failed, the retry intentionally fails closed. Investigate the release/tag and use a new version; do not force-move a desktop tag or silently substitute artifacts. If the final artifact upload alone failed, retrieve desktop-downloads.json from the exact release and run the same public verifier.

## macOS-only transition

New releases contain only the macOS DMG. The updater and website accept both these manifests and historical manifests containing a Windows asset; no Windows app is built, tested or published. Keep the existing published manifest and release assets intact until a new release is verified.

Older installed Mac apps require both platform entries and cannot parse a new macOS-only manifest. Their first upgrade to this version must be downloaded manually from the website. Include this instruction when announcing the first macOS-only release. Subsequent checks use the updated parser. Do not fabricate a Windows asset or reuse a previous version's installer to satisfy the old parser.

## Production releases: deliberately disabled

Selecting production always fails before building or publishing. Neither an ad-hoc signature nor the existence of secrets enables production. Enabling production requires a separately reviewed change with tests proving that unsigned, unnotarized, expired/invalid, missing-identity and verification-failure paths cannot publish.

A realistic future setup is a protected release environment with a dedicated Apple Developer ID Application certificate and notarization identity. Keep those in GitHub environment secrets or a managed signer; never in source, artifacts, logs or frontend configuration. Use ephemeral runner keychains and remove them on every exit. Do not use a developer's login keychain or auto-select the first certificate.

The macOS signing implementation must sign nested executables and the app with hardened runtime and timestamp, verify the designated identity and `codesign --verify --deep --strict`, submit the final distribution to `xcrun notarytool submit --wait`, require Accepted, staple, validate the staple, and run Gatekeeper assessment on the distribution. Hashes/manifests must be generated after every signing/stapling mutation. Native clean-machine installation testing is still required. This is a setup specification, not a claim that a production signing path is implemented or verified.

Release notes and website labels must change only after that verified path exists; their schema currently accepts only unsigned prereleases.

## Unsigned first-launch rehearsal

Artifact-only CI checks application behavior and ad-hoc signature integrity. It does not claim notarization or browser/Gatekeeper acceptance. Before recommending an unsigned candidate, use a fresh Apple Silicon Mac account or a reset macOS VM:

1. Download the exact candidate DMG through Safari so quarantine is applied. Record its SHA-256, app version, source commit and macOS version with the release evidence.
2. Open the DMG, drag Umbod to Applications, eject the DMG, and open the installed app through Finder. Expect the unsigned-app warning; verify the system’s per-app Open Anyway flow works. Do not disable Gatekeeper or remove quarantine as a workaround.
3. With disposable test data, verify backend startup, connector discovery and a tool call. Close/reopen, restart the backend and quit. Repeat launch without changing credentials or security settings; record any prompts.
4. Check the installed bundle signature after execution. Preserve failure evidence and fix failures before recommending the candidate.

Current CI runs on macOS 26 ARM64 and checks binary deployment requirements against macOS 14. This is not runtime verification on macOS 14; that lane remains follow-up work. Native dependencies built from source use MACOSX_DEPLOYMENT_TARGET=14.0 and do not reuse potentially incompatible cached build wheels.
