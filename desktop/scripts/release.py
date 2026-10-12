#!/usr/bin/env python3
"""Desktop-only release policy and deterministic public metadata. No publishing here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

DESKTOP = Path(__file__).resolve().parents[1]
REPOSITORY = 'computerlovetech/umbod'
VERSION_PATTERN = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def check_version(value):
    if not re.fullmatch(VERSION_PATTERN, value):
        raise ValueError('Expected a desktop X.Y.Z version, without prefix or suffix')
    return value


def version():
    return check_version((DESKTOP / 'VERSION').read_text().strip())


def guard(*, version, confirmation, mode, rights_confirmed, repository, ref, event, expected_version):
    check_version(version)
    if repository != REPOSITORY or ref != 'refs/heads/main' or event != 'workflow_dispatch':
        raise ValueError('Release requires manual dispatch from computerlovetech/umbod main')
    if version != expected_version:
        raise ValueError('Dispatch version must match desktop/VERSION')
    if mode != 'unsigned-prerelease':
        raise ValueError('Production releases are disabled: verified signing and notarization are not configured')
    if rights_confirmed is not True:
        raise ValueError('Confirm redistribution rights and dependency notices before publishing')
    tag = f'desktop-v{version}'
    if confirmation != f'release {tag} {mode}':
        raise ValueError(f'Intentional confirmation must be: release {tag} {mode}')
    return tag


def metadata(folder, release_version, commit):
    check_version(release_version)
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('A full source commit SHA is required')
    tag = f'desktop-v{release_version}'
    base = f'https://github.com/{REPOSITORY}/releases/download/{tag}/'
    names = {'macos-arm64': f'Umbod-{release_version}-arm64.dmg'}
    outputs = {'desktop-downloads.json', 'SHA256SUMS', 'RELEASE_NOTES.md'}
    for path in folder.iterdir():
        if path.name not in set(names.values()) | outputs:
            raise ValueError(f'Unexpected release artifact: {path.name}')
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Unsafe release artifact: {path.name}')
    assets = {}
    for platform, name in names.items():
        path = folder / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing, empty or unsafe artifact: {name}')
        assets[platform] = {'url': base + name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}
    manifest = {'schemaVersion': 1, 'status': 'available', 'version': release_version,
                'tag': tag, 'sourceCommit': commit, 'channel': 'unsigned-prerelease', 'assets': assets}
    (folder / 'desktop-downloads.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (folder / 'SHA256SUMS').write_text(''.join(f'{assets[p]["sha256"]}  {name}\n' for p, name in names.items()))
    (folder / 'RELEASE_NOTES.md').write_text(
        f'# Umbod Desktop {release_version} — UNSIGNED PRERELEASE\n\n'
        f'Source: `{commit}` · desktop tag: `{tag}`. Independent of Kubernetes and SDK versions.\n\n'
        'macOS: Apple Silicon, macOS 14 or later; ad-hoc signed, NOT notarized. '
        'OS security acceptance is not certified. Do not disable system security.\n\n'
        'Mount the DMG and copy Umbod.app to Applications. Closing the window leaves the backend running; '
        'use Settings to stop it. Credentials stay in the OS vault.\n\n'
        'macOS now uses the shared Python backend with the native SwiftUI interface; '
        'the interpreter is bundled, so Docker and an external Python installation are not required. '
        'Existing Mac settings are imported with a '
        'backup and resumable migration; reconnect MCP clients to refresh tool names. '
        'Access to legacy Keychain items or a changed unsigned executable may still require '
        'macOS approval. Dependency inventories and notices are included in each installer.\n\n'
        'Upgrading from an older Mac release: download this macOS-only release manually from '
        'https://umbod.ai/download/. Older updaters require a Windows manifest entry; '
        'this version accepts macOS-only releases for subsequent checks.\n\n'
        'Verify the download against SHA256SUMS with `shasum -a 256`. '
        'The desktop-downloads.json file lists the exact versioned assets and their hashes.\n\n'
        'Limitations: macOS Apple Silicon only; no automatic update installation; no real OAuth-provider '
        'certification; no legacy SSE-only upstreams.\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['guard', 'metadata', 'version'])
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    if args.command == 'version':
        print(version())
    elif args.command == 'guard':
        print(guard(version=os.environ.get('DESKTOP_VERSION', ''), confirmation=os.environ.get('CONFIRMATION', ''), mode=os.environ.get('RELEASE_MODE', ''), rights_confirmed=os.environ.get('RIGHTS_CONFIRMED') == 'true', repository=os.environ.get('GITHUB_REPOSITORY'), ref=os.environ.get('GITHUB_REF'), event=os.environ.get('GITHUB_EVENT_NAME'), expected_version=version()))
    else:
        if args.directory is None:
            parser.error('--directory is required for metadata')
        metadata(args.directory, version(), os.environ.get('GITHUB_SHA', ''))


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error))
