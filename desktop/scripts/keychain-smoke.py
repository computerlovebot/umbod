#!/usr/bin/env python3
"""Real Keychain persistence check, restricted to disposable GitHub-hosted runners."""
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import tempfile
import urllib.request


def security(*arguments):
    return subprocess.check_output(["/usr/bin/security", *arguments], text=True).strip()


def worker(app, directory):
    from umbod_desktop.main import credential_namespace
    from umbod_desktop.security import KeychainVault

    profile = (app / "Contents/Resources/umbod-profile").read_text().strip()
    vault = KeychainVault(profile, credential_namespace(directory, profile))
    legacy_secret = secrets.token_urlsafe(48)
    vault.set("upstream:fixture-token", legacy_secret)
    previous = None
    for _ in range(2):
        host = subprocess.Popen([str(app / "Contents/MacOS/umbod-desktop"), "serve", "--profile", profile, "--data-dir", str(directory)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            record = json.loads(host.stdout.readline())
            token = record["admin_token"]
            request = urllib.request.Request("http://" + record["management"] + "/desktop/health", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
            stored = json.loads(subprocess.check_output([str(app / "Contents/MacOS/umbod-desktop"), "credential", "--profile", profile, "--data-dir", str(directory)], text=True, timeout=15))
            assert stored["admin_token"] == token
            assert previous is None or previous == token
            assert vault.get("upstream:fixture-token") == legacy_secret
            previous = token
        finally:
            host.stdin.close()
            try:
                host.wait(timeout=15)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()
    assert not (directory / "fixture-credentials.json").exists()
    print("PASS: real isolated Keychain, repeated credential reads and restart continuity")


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("Real Keychain tests run only on disposable GitHub-hosted runners")
    app = Path(sys.argv[1]).resolve()
    if len(sys.argv) == 4 and sys.argv[2] == "--worker":
        worker(app, Path(sys.argv[3]))
        return
    original_default = shlex.split(security("default-keychain", "-d", "user"))[0]
    original_search = shlex.split(security("list-keychains", "-d", "user"))
    with tempfile.TemporaryDirectory(prefix="umbod-keychain-ci-") as temporary:
        root = Path(temporary)
        keychain = str(root / "fixture.keychain-db")
        password = secrets.token_urlsafe(32)
        security("create-keychain", "-p", password, keychain)
        try:
            security("set-keychain-settings", "-lut", "3600", keychain)
            security("unlock-keychain", "-p", password, keychain)
            security("list-keychains", "-d", "user", "-s", keychain)
            security("default-keychain", "-d", "user", "-s", keychain)
            subprocess.run([str(app / "Contents/Resources/python/bin/python3"), "-I", "-B", str(Path(__file__).resolve()), str(app), "--worker", str(root / "data")], check=True, timeout=90)
        finally:
            security("default-keychain", "-d", "user", "-s", original_default)
            security("list-keychains", "-d", "user", "-s", *original_search)
            security("delete-keychain", keychain)


if __name__ == "__main__":
    main()
