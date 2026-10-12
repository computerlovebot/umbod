import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/audit-macos-bundle.py'
spec = importlib.util.spec_from_file_location('macos_bundle', SCRIPT)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class MacBundleTests(unittest.TestCase):
    def test_rejects_external_and_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'Non-relocatable'):
                bundle.check_reference('/opt/homebrew/lib/example.dylib', root, root, [], root)
            with self.assertRaisesRegex(ValueError, 'Unresolved'):
                bundle.check_reference('@rpath/missing.dylib', root, root, ['@loader_path'], root)
            (root / 'escape').symlink_to(SCRIPT)
            with self.assertRaisesRegex(ValueError, 'External'):
                bundle.contained(root / 'escape', root)

    def test_accepts_bundled_and_system_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test.dylib').write_bytes(b'fixture')
            bundle.check_reference('@rpath/test.dylib', root, root, ['@loader_path'], root)
            bundle.check_reference('/usr/lib/libSystem.B.dylib', root, root, [], root)

    def test_load_commands_distinguish_dylib_identity_from_dependencies(self):
        result = bundle.load_commands('''Load command 1
          cmd LC_ID_DYLIB
      cmdsize 64
         name bazel-out/build-path.so (offset 24)
Load command 2
          cmd LC_LOAD_DYLIB
      cmdsize 64
         name @rpath/required.dylib (offset 24)
Load command 3
          cmd LC_BUILD_VERSION
        minos 14.0
''')
        self.assertEqual([c['cmd'] for c in result], ['LC_ID_DYLIB', 'LC_LOAD_DYLIB', 'LC_BUILD_VERSION'])
        self.assertEqual(result[1]['name'], '@rpath/required.dylib')
        self.assertEqual(result[2]['minos'], '14.0')

    def test_acceptance_has_no_checkout_or_compilation(self):
        workflow = (SCRIPT.parents[2] / '.github/workflows/desktop-build.yml').read_text()
        job = workflow.split('  macos-acceptance:\n')[1]
        self.assertIn('needs: macos', job)
        self.assertNotIn('actions/checkout', job)
        self.assertNotIn('setup-python', job)
        self.assertIn('macos-acceptance-kit', job)
        runner = (SCRIPT.parent / 'accept-macos-artifact.sh').read_text()
        self.assertNotIn('swift run', runner)
        self.assertIn('UMBOD_TEST_APP="$APP"', runner)
