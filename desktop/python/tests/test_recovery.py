import json

import pytest
from umbod.rest.authentication.authorization import JwtVerificationError
from umbod_desktop.client_setup import ClientSetup
from umbod_desktop.configuration import desktop_settings
from umbod_desktop.security import DesktopAdminVerifier, DesktopAgentVerifier
from umbod_desktop.storage import DesktopState


def test_desktop_configuration_never_uses_development_authentication(tmp_path):
    settings = desktop_settings(tmp_path, "http://127.0.0.1:12345", "unique-secret" * 5)
    assert settings.runtime.auth == "desktop"
    assert settings.admin_authentication.mode == "jwt"
    assert settings.admin_authentication.environment == "production"
    assert settings.connector_store.type == "sqlite"
    assert not settings.rest.metrics_enabled
    assert not settings.mcp.metrics_enabled
    assert settings.connector_security.configuration_secret
    assert (
        settings.connector_security.approval_state_key
        != settings.connector_security.configuration_secret
    )


async def test_desktop_tokens_do_not_accept_development_credentials():
    verifier = DesktopAdminVerifier("admin-secret")
    with pytest.raises(JwtVerificationError):
        verifier.verify(
            '{"signature":"trusted","claims":{"sub":"attacker","groups":["desktop-owner"]}}'
        )
    assert (
        await DesktopAgentVerifier("agent-secret").verify_token("admin-secret") is None
    )


def test_client_preview_detects_concurrent_changes_and_preserves_other_entries(
    tmp_path,
):
    state = DesktopState(tmp_path)
    setup = ClientSetup(state, tmp_path, "dev")
    path = tmp_path / "agent.json"
    executable = tmp_path / "bridge"
    executable.write_text("fixture")
    original = {"mcpServers": {"other": {"command": "unchanged"}}, "theme": "dark"}
    path.write_text(json.dumps(original))
    preview = setup.preview({"path": str(path), "command": str(executable)})
    assert "--data-dir" in preview["entry"]["args"]
    path.write_text('{"modified":true}')
    with pytest.raises(ValueError, match="changed"):
        setup.apply({"preview": preview["id"], "consent": True})
    path.write_text(json.dumps(original))
    setup.apply({"preview": preview["id"], "consent": True})
    after = json.loads(path.read_text())
    assert after["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert after["theme"] == "dark"
    setup.undo({"consent": True})
    assert json.loads(path.read_text()) == original


def test_client_setup_rejects_symlinks(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        ClientSetup(DesktopState(tmp_path), tmp_path, "dev").preview(
            {"path": str(link), "command": str(target)}
        )


async def test_legacy_agent_credentials_keep_only_agent_access(tmp_path):
    import hashlib

    from umbod_desktop.legacy import saved_agent_hashes, saved_port

    old_token = "existing-private-agent-token"
    document = {
        "gateway_port": 19432,
        "connection": {
            "id": "old",
            "token_hash": hashlib.sha256(old_token.encode()).hexdigest(),
        },
        "clients": [{"token_hash": "invalid"}],
    }
    (tmp_path / "config.json").write_text(json.dumps(document))
    hashes = saved_agent_hashes(tmp_path)
    assert len(hashes) == 1
    verifier = DesktopAgentVerifier("new-token", tuple(hashes))
    assert await verifier.verify_token(old_token) is not None
    assert await verifier.verify_token("wrong-token") is None
    with pytest.raises(JwtVerificationError):
        DesktopAdminVerifier("admin-token").verify(old_token)
    assert saved_port(tmp_path) == 19432
    (tmp_path / "python-endpoint.json").write_text('{"port":19433}')
    assert saved_port(tmp_path) == 19433


async def test_existing_encrypted_database_never_generates_replacement_key(tmp_path):
    from test_runtime import MemoryVault
    from umbod_desktop.runtime import create_desktop_app

    (tmp_path / "backend.sqlite3").touch()
    vault = MemoryVault()
    with pytest.raises(ValueError, match="encryption key is missing"):
        await create_desktop_app(
            tmp_path, "dev", "http://127.0.0.1:1234", vault, lambda: None
        )
    assert vault.values == {}


def test_client_undo_restores_original_bytes(tmp_path):
    state = DesktopState(tmp_path)
    setup = ClientSetup(state, tmp_path, "dev")
    path = tmp_path / "agent.json"
    before = b'{\n  "theme": "dark",\n  "mcpServers": {}\n}\n'
    path.write_bytes(before)
    executable = tmp_path / "bridge"
    executable.touch()
    preview = setup.preview({"path": str(path), "command": str(executable)})
    setup.apply({"preview": preview["id"], "consent": True})
    setup.undo({"consent": True})
    assert path.read_bytes() == before


def test_fixture_credentials_never_touch_keychain_or_normal_app_data(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import umbod_desktop.main as entrypoint
    from umbod_desktop.testing import FixtureVault

    def unexpected_keychain(*args):
        raise AssertionError("Routine tests must never open the user's Keychain")

    monkeypatch.setattr(entrypoint, "KeychainVault", unexpected_keychain)
    directory = tmp_path / "umbod-test-vault"
    directory.mkdir()
    arguments = SimpleNamespace(
        test_credentials=True, data_dir=directory, profile="dev"
    )
    vault = entrypoint.credential_vault(arguments, directory)
    vault.set("python:admin-token", "dummy-fixture-value")
    assert (
        entrypoint.credential_vault(arguments, directory).get("python:admin-token")
        == "dummy-fixture-value"
    )
    assert vault.path.stat().st_mode & 0o777 == 0o600
    arguments.test_credentials = False
    with pytest.raises(ValueError, match="explicitly select"):
        entrypoint.credential_vault(arguments, directory)
    with pytest.raises(ValueError, match="temporary directory"):
        FixtureVault(tmp_path / "Umbod")


def test_fixture_bridge_survives_client_removing_tmpdir(tmp_path, monkeypatch):
    import tempfile

    from umbod_desktop.testing import FixtureVault

    directory = tmp_path / "umbod-test-bridge"
    directory.mkdir()
    original = FixtureVault(directory)
    original.set("python:agent-token", "dummy")
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", "/tmp")
    assert FixtureVault(directory).get("python:agent-token") == "dummy"
