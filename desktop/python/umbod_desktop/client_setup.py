"""Previewed, recoverable agent configuration edits with optimistic conflict checks."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .storage import atomic_bytes, atomic_json


def read_configuration(path: Path) -> bytes | None:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(part.is_symlink() for part in (path, *path.parents))
    ):
        raise ValueError(
            "Agent configuration must be an absolute path without symlinks"
        )
    if not path.exists():
        return None
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Agent configuration is too large")
    return path.read_bytes()


def digest(value: bytes | None) -> str:
    return hashlib.sha256(value or b"").hexdigest()


class ClientSetup:
    def __init__(self, state, directory, profile):
        self.state, self.directory, self.profile = state, directory, profile
        self.previews = {}

    def preview(self, body):
        if self.state.data.get("client_setup"):
            raise ValueError(
                "Restore the existing backup before replacing agent configuration"
            )
        path, command = Path(body["path"]), Path(body["command"])
        if not command.is_absolute() or not command.is_file():
            raise ValueError("Bundled bridge executable is missing")
        before = read_configuration(path)
        document = json.loads(before) if before is not None else {}
        if not isinstance(document, dict) or not isinstance(
            document.get("mcpServers", {}), dict
        ):
            raise TypeError("Agent configuration must contain an MCP server object")
        name = "umbod-dev" if self.profile == "dev" else "umbod"
        if name in document.get("mcpServers", {}):
            raise ValueError(
                "An Umbod entry already exists; remove it explicitly before replacing it"
            )
        entry = {"command": str(command), "args": ["bridge", "--profile", self.profile]}
        # Isolated test directories must never connect an agent to real app data.
        from .main import default_directory

        if self.directory != default_directory(self.profile):
            entry["args"] += ["--data-dir", str(self.directory)]
            if (self.directory / "fixture-credentials.json").exists():
                entry["args"].append("--test-credentials")
        document.setdefault("mcpServers", {})[name] = entry
        identifier = uuid4().hex
        backup = path.with_name(path.name + f".umbod-{identifier}.backup")
        preview = {
            "id": identifier,
            "path": str(path),
            "backup": str(backup),
            "entry_name": name,
            "entry": entry,
        }
        self.previews[identifier] = (preview, before, document)
        return preview

    def apply(self, body):
        if body.get("consent") is not True:
            raise ValueError("Confirm the configuration preview first")
        preview, before, document = self.previews[body["preview"]]
        path, backup = Path(preview["path"]), Path(preview["backup"])
        if read_configuration(path) != before:
            raise ValueError("Agent configuration changed; preview again")
        path.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(
            os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as stream:
            stream.write(before or b"")
            stream.flush()
            os.fsync(stream.fileno())
        receipt = {
            "path": str(path),
            "backup": str(backup),
            "before_hash": digest(before),
            "existed": before is not None,
            "after_hash": digest(json.dumps(document).encode()),
        }
        # Save recovery metadata before mutating the agent's file.
        self.state.data["client_setup"] = receipt
        self.state.save()
        atomic_json(path, document)
        self.previews.pop(body["preview"], None)
        if "activation" in self.state.data:
            self.state.data["activation"]["configured"] = True
        self.state.save()
        return receipt

    def undo(self, body):
        if body.get("consent") is not True:
            raise ValueError("Confirm backup restoration first")
        receipt = self.state.data["client_setup"]
        path, backup = Path(receipt["path"]), Path(receipt["backup"])
        current = read_configuration(path)
        if digest(current) not in (receipt["after_hash"], receipt["before_hash"]):
            raise ValueError("Agent configuration changed; restore the backup manually")
        before = read_configuration(backup)
        if digest(before) != receipt["before_hash"]:
            raise ValueError("Backup integrity check failed")
        if receipt["existed"]:
            atomic_bytes(path, before)
        else:
            path.unlink(missing_ok=True)
        self.state.data.pop("client_setup", None)
        if "activation" in self.state.data:
            self.state.data["activation"]["configured"] = False
        self.state.save()
        return {"status": "restored"}
