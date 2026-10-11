#!/usr/bin/env python3
"""Audit release layout and Mach-O dependencies without loading application code."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

MAGICS = {bytes.fromhex(x) for x in ('cffaedfe', 'feedfacf', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
SYSTEM = ('/usr/lib/', '/System/Library/')


def contained(path, root):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'External bundle reference: {path}')
    if not path.exists():
        raise ValueError(f'Missing bundle dependency: {path}')


def load_commands(text):
    result = []
    current = None
    for line in text.splitlines():
        fields = line.strip().split()
        if fields[:1] == ['cmd']:
            current = {'cmd': fields[1]}
            result.append(current)
        elif current is not None and fields and fields[0] in ('name', 'path', 'minos', 'version'):
            current[fields[0]] = line.strip().split(' ', 1)[1].split(' (offset')[0]
    return result


def expand(value, loader, executable):
    return Path(value.replace('@loader_path', str(loader)).replace('@executable_path', str(executable)))


def check_reference(value, loader, executable, rpaths, root):
    if value.startswith(SYSTEM):
        return  # System libraries can live only in dyld's shared cache.
    if value.startswith('@rpath/'):
        suffix = value[len('@rpath/'):]
        for rpath in rpaths:
            candidate = expand(rpath, loader, executable) / suffix
            if str(candidate).startswith(SYSTEM):
                # Swift's OS runtime is supplied by macOS, not the Xcode toolchain.
                if str(candidate).startswith('/usr/lib/swift/libswift'):
                    return
            elif candidate.exists():
                contained(candidate, root)
                return
        raise ValueError(f'Unresolved library: {value} in {loader}')
    if not value.startswith(('@loader_path/', '@executable_path/')):
        raise ValueError(f'Non-relocatable library: {value}')
    contained(expand(value, loader, executable), root)


def audit(app):
    app = app.resolve()
    contents = app / 'Contents'
    metadata = plistlib.loads((contents / 'Info.plist').read_bytes())
    if metadata['LSMinimumSystemVersion'] != '14.0':
        raise ValueError('Expected macOS 14 compatibility target')
    required = ['MacOS/Umbod', 'MacOS/umbod-desktop', 'MacOS/umbod-gateway', 'Resources/python/bin/python3']
    for name in required:
        path = contents / name
        contained(path, app)
        if not os.access(path, os.X_OK):
            raise ValueError(f'Missing executable permission: {name}')
    for name in ['Resources/runtime-id', 'Resources/umbod-profile', 'Resources/UmbodBrand.icns', 'Resources/build-metadata.json']:
        contained(contents / name, app)
    identity = json.loads((contents / 'Resources/build-metadata.json').read_text())
    if identity['version'] != metadata['CFBundleShortVersionString']:
        raise ValueError('Build metadata and app versions disagree')
    binaries = 0
    for path in contents.rglob('*'):
        if path.is_symlink():
            contained(path, app)
            continue
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) not in MAGICS:
                continue
        binaries += 1
        arches = subprocess.check_output(['/usr/bin/lipo', '-archs', str(path)], text=True).split()
        if 'arm64' not in arches:
            raise ValueError(f'No ARM64 slice: {path}')
        commands = load_commands(subprocess.check_output(['/usr/bin/otool', '-arch', 'arm64', '-l', str(path)], text=True))
        python = contents / 'Resources/python'
        executable = python / 'bin' if path.is_relative_to(python) else contents / 'MacOS'
        rpaths = [c['path'] for c in commands if c['cmd'] == 'LC_RPATH']
        # Python extension libraries also inherit the interpreter's run path.
        if path.is_relative_to(python):
            rpaths += ['@executable_path/../lib']
        for value in rpaths:
            if not value.startswith(SYSTEM):
                contained(expand(value, path.parent, executable), app)
        for command in commands:
            if command['cmd'] in ('LC_BUILD_VERSION', 'LC_VERSION_MIN_MACOSX'):
                version = command.get('minos', command.get('version'))
                parts = tuple(map(int, version.split('.')))
                if (parts + (0, 0))[:2] > (14, 0):
                    raise ValueError(f'Requires macOS {version}, newer than target: {path}')
            if command['cmd'] in ('LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB', 'LC_LOAD_UPWARD_DYLIB'):
                check_reference(command['name'], path.parent, executable, rpaths, app)
    if not binaries:
        raise ValueError('No native binaries found')
    print(f'PASS: {binaries} ARM64 binaries, macOS 14 target, resources, symlinks and library references')


if __name__ == '__main__':
    audit(Path(sys.argv[1]))
