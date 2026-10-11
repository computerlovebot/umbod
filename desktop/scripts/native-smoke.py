#!/usr/bin/env python3
"""Verify a real SwiftUI window using isolated app preferences and fixture credentials."""
import json
import os
import pathlib
import plistlib
import subprocess
import sys
import tempfile
import time
import uuid


def default_app():
    desktop = pathlib.Path(__file__).resolve().parents[1]
    version = (desktop / 'VERSION').read_text().strip()
    return desktop / 'dist' / f'Umbod-{version}.app'


def main():
    release_identity = '--release-identity' in sys.argv
    if release_identity and (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise SystemExit('Unchanged release identity tests require a disposable GitHub-hosted runner')
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else default_app()).resolve()
    with tempfile.TemporaryDirectory(prefix='umbod-test-native-smoke-') as temp:
        root = pathlib.Path(temp).resolve()
        app = root / 'Umbod Smoke.app'
        subprocess.run(['/usr/bin/ditto', str(source), str(app)], check=True)
        if not release_identity:
            # Local smoke tests must not share a user's window restoration identity.
            plist = app / 'Contents/Info.plist'
            metadata = plistlib.loads(plist.read_bytes())
            metadata['CFBundleIdentifier'] += '.fixture.' + uuid.uuid4().hex
            plist.write_bytes(plistlib.dumps(metadata))
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)], check=True, stderr=subprocess.DEVNULL)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        report = root / 'window.json'
        directory = root / 'umbod-test-data'
        environment = os.environ.copy()
        environment['PATH'] = '/usr/bin:/bin'
        environment.pop('PYTHONHOME', None)
        environment.pop('PYTHONPATH', None)
        process = subprocess.Popen(['/usr/bin/open', '-n', '-W', '-a', str(app), '--args', '--data-dir', str(directory), '--test-credentials', '--smoke-report', str(report), '--smoke-close-reopen', '--smoke-exit'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment)
        # Deliver a reopen event once LaunchServices has registered the isolated app.
        time.sleep(1)
        subprocess.run(['/usr/bin/open', '-a', str(app)], check=True)
        try:
            status = process.wait(timeout=90)
            assert status == 0, f'App exited with {status}'
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=8)
            # Only stop the exact disposable app launched by this test.
            processes = subprocess.check_output(['/bin/ps', '-axo', 'pid=,command='], text=True)
            executable = str(app / 'Contents/MacOS/Umbod') + ' '
            for line in processes.splitlines():
                pid, _, command = line.strip().partition(' ')
                if command.lstrip().startswith(executable):
                    os.kill(int(pid), 15)
            raise AssertionError('Native app did not finish smoke lifecycle within 90 seconds')
        state = json.loads(report.read_text())
        print(json.dumps(state, indent=2), flush=True)
        assert state['backgroundSurvivedClose'] is True
        assert state['reopened'] is True
        assert state['serverCount'] == 0
        assert state['backendRunning'] is True
        assert any(w['visible'] and w['width'] >= 950 and w['height'] >= 680 for w in state['windows'])
        assert state['bundlePath'] == str(app)
        try:
            os.kill(state['backendPID'], 0)
            raise AssertionError('Bundled backend survived normal app termination')
        except ProcessLookupError:
            pass
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        if release_identity:
            assert state['bundleIdentifier'] == 'app.umbod.desktop'
            print('PASS: unchanged release identity launched through LaunchServices')
        print('PASS: isolated bundled SwiftUI window, authenticated backend, close/reopen and normal termination; no Keychain access')


if __name__ == '__main__':
    main()
