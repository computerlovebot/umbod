"""Explicit disposable-fixture credentials. Never selected as a Keychain fallback."""

import json
import os
import sys
import tempfile
from pathlib import Path

from .storage import atomic_json


class FixtureVault:
    def __init__(self, directory: Path):
        root = directory.resolve()
        temporary_roots = [Path(tempfile.gettempdir()).resolve()]
        if sys.platform == "darwin":
            # _CS_DARWIN_USER_TEMP_DIR also works when an MCP client drops TMPDIR.
            temporary_roots.append(Path(os.confstr(65537)).resolve())
        if not any(
            root.is_relative_to(path) for path in temporary_roots
        ) or not root.name.startswith("umbod-test-"):
            raise ValueError(
                "Test credentials require an explicit umbod-test-* temporary directory"
            )
        if directory.is_symlink() or root.stat().st_uid != os.getuid():
            raise ValueError("Test directory must belong to the current user")
        self.path = root / "fixture-credentials.json"

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, reference):
        return self.read().get(reference)

    def set(self, reference, value):
        document = self.read()
        document[reference] = value
        atomic_json(self.path, document)

    def delete(self, reference):
        document = self.read()
        document.pop(reference, None)
        atomic_json(self.path, document)
