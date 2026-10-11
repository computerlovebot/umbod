import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify-python-bundle.py"
spec = importlib.util.spec_from_file_location("verify_python_bundle", SCRIPT)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class PythonBundleTests(unittest.TestCase):
    def test_accepts_bundled_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle.verify_installation(root, [root / "lib/python314.zip"], [])

    def test_rejects_checkout_on_import_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "external path"):
                bundle.verify_installation(Path(directory), [SCRIPT.parent], [])

    def test_rejects_editable_distribution_even_with_import_hook(self):
        distribution = Mock(metadata={"Name": "umbod-core"})
        distribution.read_text.return_value = '{"dir_info": {"editable": true}}'
        with self.assertRaisesRegex(ValueError, "Editable distribution"):
            bundle.verify_installation(SCRIPT.parent, [], [distribution])

    def test_rejects_pth_pointing_to_missing_ci_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "lib/python3.14/site-packages"
            site.mkdir(parents=True)
            (site / "_umbod_core.pth").write_text("/Users/runner/work/umbod/umbod/umbod/api/src\n")
            with self.assertRaisesRegex(ValueError, "external path"):
                bundle.verify_installation(root, [], [])
