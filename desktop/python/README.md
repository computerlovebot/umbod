# macOS desktop host

The SwiftUI app keeps its native screens. `AdministrationClient.swift` maps the shared `/api/admin` connector, discovery, publication, activation and group-permission APIs to the existing native presentation model. The host composes those REST and MCP applications; it does not implement a second connector registry or permission engine.

## Entry points and ownership

- `main.py`: packaged `serve` and `bridge` commands, loopback socket, stable port, process lock, readiness pipe, owner shutdown and dev/release isolation. Its `credential` command lets Swift reattach through a private pipe using the same installed backend identity; Swift does not access Keychain independently. Legacy positional bridge identities remain accepted. `build.sh` bundles a relocatable interpreter and locked dependencies, then signs a fresh bundle.
- `runtime.py`, `configuration.py`: shared application composition and authenticated `/desktop` routes. SQL event polling synchronizes API writes with MCP. Dedicated metrics listeners are disabled for desktop.
- `security.py`: separate random admin, agent, upstream and encryption credentials in macOS Keychain. No development auth or plaintext fallback. Existing agent token hashes are retained for migration; they never grant administration access.
- `upstreams.py`, `models.py`: validated stdio and Streamable HTTP transports exposed through private authenticated loopback proxies to the shared downstream connector API. A proxy owns its lifespan in one task. Offline drafts remain editable and cannot retain an obsolete live transport after an invalid edit.
- `oauth.py`: native browser callback coordination and Keychain storage around the shared OAuth/PKCE adapter. Refresh uses the shared locking behavior; compare-and-swap storage prevents a stale refresh from restoring logged-out credentials.
- `migration.py`, `legacy.py`: authenticated retirement of the old process, resumable settings import, OAuth credential conversion and stable endpoint/client identity preservation. Original settings and Keychain entries are preserved. No PID from disk is signalled.
- `storage.py`, `usage.py`: owner-only atomic host metadata and aggregate call counts, without arguments or results. Shared connectors and encrypted configuration live in `backend.sqlite3`.
- `client_setup.py`: consented configuration previews, conflict detection and byte-preserving backup restoration.
- `testing.py`: explicitly selected fixture credentials, restricted to owned `umbod-test-*` directories under the system temporary directory. This is never a fallback for unavailable Keychain access; normal profiles always use Keychain.
- `tests/`: real HTTP/stdio MCP calls, default-deny and live revocation, resumable import, authentication isolation, OAuth refresh/callback races and safe client-file editing. Native tests additionally exercise the packaged interpreter, an explicit disposable fixture vault and persistent-process reattachment. Routine tests never open the user’s Keychain. The window smoke test uses a disposable bundle identity so it also avoids sharing the user’s window-restoration preferences.

## Shared backend extension points

The changes outside desktop are limited to deployment composition: an explicitly supplied REST identity verifier, optional REST/MCP metrics listeners (enabled by default), SQL-backed group permission reloads, and an injectable MCP invocation sink. Enterprise verifier selection and domain behavior retain their defaults. Desktop authentication is fixed to one local owner and one permission group.

The desktop host provides authenticated stdio/HTTP transport adapters instead of adding desktop subprocess, Keychain or browser lifecycle behavior to the shared core. The REST API remains the authority for connector discovery, tool activation, publication and permissions.

## Recovery and lifecycle

A persistent launch installs an immutable runtime under the profile's `runtimes/<build-id>/Contents`, with stable bridge links under `bin/`. Closing the app leaves it running; reopening authenticates and checks its profile/PID. A new app build reports a restart requirement while the existing process continues. A saved-port conflict or missing encryption credential fails closed rather than generating new identities or silently changing the endpoint.

Migration writes `config.before-python.json` and a journal in `desktop-v2.json`; repeated imports recover connectors by deterministic public path. Failed imports preserve their original source and display a repair message. Do not delete the SQLite database or Keychain root secret to retry. Existing bridge command paths and HTTP credentials are retained, but clients must rediscover the shared backend's tool names. The current native workspace uses connector setup and Settings → MCP.

Run `uv run --locked pytest` and `uv run --locked ruff check .` here. From `desktop/`, `bash scripts/verify.sh` builds and verifies the actual macOS bundle. Shared application changes also require the API/MCP tests and `bash umbod/tests/kind-runtime/run.sh` from the repository root. Ad-hoc local verification is not clean-machine Gatekeeper/notarization certification.

CI runs `scripts/keychain-smoke.py` only on disposable GitHub-hosted runners, using a newly created temporary Keychain that is removed afterward. It verifies real credential reads and restart continuity. This is not a test of approval prompts for a particular user’s legacy Keychain items. A locked Keychain or the first access to legacy items may still need approval; production signing must provide a stable application identity across interpreter upgrades. Local builds remain ad-hoc signed. Routine verification does not ask for a password or change Keychain access controls.
