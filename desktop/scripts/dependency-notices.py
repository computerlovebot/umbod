#!/usr/bin/env python3
"""Preserve dependency notices from the exact installed/build inputs. No network access."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

DESKTOP = Path(__file__).resolve().parents[1]
SUPPLEMENTS = DESKTOP / "licenses"


def is_notice(path):
    return path.name.lower().startswith(("license", "licence", "copying", "notice", "copyright", "third-party", "thirdparty")) and path.suffix not in {".py", ".pyc"}


def supplement(key):
    sources = json.loads((SUPPLEMENTS / "sources.json").read_text())
    entry = sources.get(key)
    if entry is None:
        raise ValueError(f"Missing dependency notice: {key}; review and add a version-pinned source")
    path = SUPPLEMENTS / entry["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["notice_sha256"]:
        raise ValueError(f"Supplemental notice checksum mismatch: {key}")
    return [(entry["source"], path.read_text())]


def python_entries():
    for dist in sorted(importlib.metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        name, version = dist.metadata["Name"], dist.version
        if name in {"umbod", "umbod-core", "umbod-desktop"}:
            continue
        files = [(str(path), dist.locate_file(path).read_text(errors="replace")) for path in dist.files or [] if is_notice(Path(path)) and dist.locate_file(path).is_file()]
        yield name, version, dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See retained notices", files or supplement(f"{name}-{version}")
    version = ".".join(map(str, sys.version_info[:3]))
    build = (Path(sys.base_prefix) / "BUILD").read_text().strip()
    yield "CPython and bundled native libraries", f"{version}-{build}", "See retained notices", supplement(f"cpython-{version}-{build}")


def rust_entries(cargo):
    result = subprocess.run([cargo, "metadata", "--locked", "--format-version", "1", "--filter-platform", "x86_64-pc-windows-msvc"], cwd=DESKTOP, capture_output=True, text=True, check=True)
    for package in sorted(json.loads(result.stdout)["packages"], key=lambda item: item["name"]):
        if not package["source"]:
            continue
        root = Path(package["manifest_path"]).parent
        files = [(path.relative_to(root).as_posix(), path.read_text(errors="replace")) for path in sorted(root.rglob("*")) if path.is_file() and is_notice(path)]
        yield package["name"], package["version"], package["license"] or "See retained notices", files or supplement(f'{package["name"]}-{package["version"]}')


def dotnet_entries(publish):
    manifest = json.loads((publish / "Umbod.Windows.deps.json").read_text())
    # Self-contained SDK publishing preserves these notices at the output root.
    files = [(path.name, path.read_text(errors="replace")) for path in sorted(publish.iterdir()) if path.is_file() and is_notice(path)]
    if not any("third" in name.lower() for name, _ in files) or not any("license" in name.lower() for name, _ in files):
        raise ValueError("Self-contained .NET output must retain LICENSE and ThirdPartyNotices")
    versions = sorted(key for key in manifest["libraries"] if key.lower().startswith("runtimepack."))
    if not versions:
        raise ValueError("Missing self-contained .NET runtime identities")
    yield ".NET and Windows Desktop runtime", ", ".join(versions), "See retained notices", files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["python", "windows"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--publish", type=Path)
    args = parser.parse_args()
    entries = list(python_entries()) if args.platform == "python" else [*rust_entries(args.cargo), *dotnet_entries(args.publish)]
    notices = ["Umbod Desktop third-party notices\n\nUmbod source license\n" + (DESKTOP.parent / "LICENSE").read_text()]
    inventory = []
    for name, version, license_id, files in entries:
        notices.append(f"\n{'=' * 72}\n{name} {version}\nDeclared license: {license_id}")
        inventory.append({"name": name, "version": version, "declared_license": license_id, "notices": [filename for filename, _ in files]})
        for filename, text in files:
            notices.append(f"\n--- {filename} ---\n{text}")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(notices), encoding="utf-8")
    (args.output / "dependency-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"Retained notices for {len(entries)} dependency entries")


if __name__ == "__main__":
    main()
