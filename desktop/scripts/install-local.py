#!/usr/bin/env python3
"""Build and install the release app locally without resetting its profile."""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

DESKTOP = Path(__file__).resolve().parents[1]
TARGET = Path('/Applications/Umbod.app')
PROFILE = Path.home() / 'Library/Application Support/Umbod'


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def validate_bundle(app: Path):
    if app.is_symlink():
        raise RuntimeError('Refusing to replace or install a symlinked app.')
    with (app / 'Contents/Info.plist').open('rb') as source:
        info = plistlib.load(source)
    if info.get('CFBundleIdentifier') != 'app.umbod.desktop' or info.get('UmbodChannel') != 'release':
        raise RuntimeError('Expected the release Umbod app, not Umbod Dev or another app.')


def gateway_running(profile: Path) -> bool:
    lock = profile / 'python.lock'
    if not lock.exists():
        return False
    with lock.open('r') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Refusing a redirect from the local gateway.')


def gateway_request(profile: Path, route: str, method='GET'):
    record = json.loads((profile / 'python-runtime.json').read_text())
    address = record.get('management', '')
    if record.get('profile') != 'release' or not re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}', address):
        raise RuntimeError('Invalid production gateway identity.')
    result = run(profile / 'bin/umbod-desktop', 'credential', '--profile', 'release',
                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15)
    token = json.loads(result.stdout)['admin_token']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(path, verb):
        req = urllib.request.Request('http://' + address + path, method=verb,
                                     headers={'Authorization': 'Bearer ' + token})
        with opener.open(req, timeout=5) as response:
            return json.load(response)

    health = request('/desktop/health', 'GET')
    if health.get('profile') != 'release' or health.get('pid') != record.get('pid') or health.get('protocol') != 2:
        raise RuntimeError('Gateway identity mismatch; nothing was stopped.')
    return health if route == '/desktop/health' else request(route, method)


def stop_gateway(profile: Path):
    if not gateway_running(profile):
        return
    gateway_request(profile, '/desktop/shutdown', 'POST')
    deadline = time.monotonic() + 20
    while gateway_running(profile):
        if time.monotonic() >= deadline:
            raise RuntimeError('Gateway did not stop. The installed app has not been replaced.')
        time.sleep(0.2)


def quit_app(target: Path):
    # Ask only this installed release UI to quit normally. Never force-kill a PID.
    run('swift', '-e', '''
import AppKit
import Foundation
let target = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
let apps = NSRunningApplication.runningApplications(withBundleIdentifier: "app.umbod.desktop")
for app in apps {
    guard app.bundleURL?.standardizedFileURL == target else {
        fputs("Another release copy is running. Quit it before installing.\\n", stderr); exit(1)
    }
}
for app in apps { if !app.terminate() { exit(1) } }
let deadline = Date().addingTimeInterval(15)
while apps.contains(where: { !$0.isTerminated }) {
    if Date() > deadline { fputs("Umbod did not quit.\\n", stderr); exit(1) }
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
}
''', target)


def replace_bundle(staged: Path, target: Path, backup: Path):
    """Same-volume renames; restore the old bundle if replacement fails."""
    had_previous = target.exists()
    if had_previous:
        backup.parent.mkdir(parents=True, exist_ok=False)
        target.rename(backup)
    try:
        staged.rename(target)
    except BaseException:
        if had_previous:
            backup.rename(target)
        raise


def wait_for_build(profile: Path, build_id: str):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if gateway_running(profile) and gateway_request(profile, '/desktop/health').get('build_id') == build_id:
                return
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            pass
        time.sleep(1)
    raise RuntimeError('App installed, but its new gateway is not ready. Open Umbod and check Settings. The previous app is retained; profile data was not rolled back.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Show the workflow without building or changing anything.')
    args = parser.parse_args()
    if args.dry_run:
        print(f'Build release → verify → quit {TARGET} and its gateway → retain previous app → install → reopen and verify.\nPreserve {PROFILE} and macOS Keychain. Umbod Dev is untouched.')
        return
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise RuntimeError('Run on macOS as your normal user, without sudo.')
    if not os.access(TARGET.parent, os.W_OK) or (TARGET.exists() and not os.access(TARGET, os.W_OK)):
        raise RuntimeError('Your user needs write access to /Applications/Umbod.app. No files were changed.')
    if TARGET.exists() or TARGET.is_symlink():
        validate_bundle(TARGET)
    with (TARGET.parent / '.umbod-local-install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix='umbod-local-build-') as output:
            print('Building release app. Your installed app keeps running during the build.', flush=True)
            run('bash', DESKTOP / 'scripts/build.sh', 'release', env={**os.environ, 'UMBOD_DIST_DIR': output})
            candidates = list(Path(output).glob('Umbod-*.app'))
            if len(candidates) != 1:
                raise RuntimeError('Expected exactly one built release app.')
            built = candidates[0]
            validate_bundle(built)
            build_id = (built / 'Contents/Resources/runtime-id').read_text().strip()
            backup = TARGET.parent / '.umbod-local-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f') / 'Umbod.app'
            with tempfile.TemporaryDirectory(prefix='.umbod-install-', dir=TARGET.parent) as temporary:
                staged = Path(temporary) / 'Umbod.app'
                run('ditto', built, staged)
                run('codesign', '--verify', '--deep', '--strict', staged)
                run(staged / 'Contents/Resources/python/bin/python3', '-I', '-B', DESKTOP / 'scripts/verify-python-bundle.py')
                print('Quitting production Umbod and stopping its gateway. Active tool calls will be interrupted.', flush=True)
                quit_app(TARGET)
                stop_gateway(PROFILE)
                replace_bundle(staged, TARGET, backup)
            if backup.exists():
                print(f'Previous app retained at {backup}', flush=True)
            run('open', TARGET)
            wait_for_build(PROFILE, build_id)
            print('Umbod installed and running. Existing connections, permissions, and Keychain credentials preserved.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        # Never reflect captured credential output or HTTP response bodies.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f'Local install stopped: {message}', file=sys.stderr)
        sys.exit(1)
