"""Local install safety checks with disposable bundles; never touches installed apps."""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import fcntl

spec = importlib.util.spec_from_file_location('install_local', Path(__file__).resolve().parents[1] / 'scripts/install-local.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class LocalInstallTests(unittest.TestCase):
    def test_rejects_dev_and_symlink_bundles(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'Umbod.app'
            (app / 'Contents').mkdir(parents=True)
            plist = app / 'Contents/Info.plist'
            plist.write_bytes(plistlib.dumps({'CFBundleIdentifier': 'app.umbod.desktop.dev', 'UmbodChannel': 'dev'}))
            with self.assertRaises(RuntimeError):
                installer.validate_bundle(app)
            plist.write_bytes(plistlib.dumps({'CFBundleIdentifier': 'app.umbod.desktop', 'UmbodChannel': 'release'}))
            installer.validate_bundle(app)
            link = Path(temporary) / 'Link.app'
            link.symlink_to(app)
            with self.assertRaises(RuntimeError):
                installer.validate_bundle(link)

    def test_replacement_preserves_previous_bundle_and_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new, backup = root / 'Umbod.app', root / 'staged.app', root / 'backup/Umbod.app'
            old.mkdir(); new.mkdir()
            (old / 'version').write_text('old')
            (new / 'version').write_text('new')
            profile = root / 'profile'
            profile.mkdir(); (profile / 'settings').write_text('preserved')
            installer.replace_bundle(new, old, backup)
            self.assertEqual((old / 'version').read_text(), 'new')
            self.assertEqual((backup / 'version').read_text(), 'old')
            self.assertEqual((profile / 'settings').read_text(), 'preserved')

    def test_failed_replacement_restores_old_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new, backup = root / 'Umbod.app', root / 'staged.app', root / 'backup/Umbod.app'
            old.mkdir(); new.mkdir()
            (old / 'version').write_text('old')
            rename = Path.rename
            def fail_staged(path, destination):
                if path == new:
                    raise OSError('fixture replacement failure')
                return rename(path, destination)
            with patch.object(Path, 'rename', fail_staged):
                with self.assertRaises(OSError):
                    installer.replace_bundle(new, old, backup)
            self.assertEqual((old / 'version').read_text(), 'old')
            self.assertTrue(new.exists())

    def test_gateway_lock_not_stale_pid_controls_running_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            self.assertFalse(installer.gateway_running(profile))
            with (profile / 'python.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(installer.gateway_running(profile))
            self.assertFalse(installer.gateway_running(profile))

    def test_refuses_nonloopback_before_reading_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            (profile / 'python-runtime.json').write_text('{"profile":"release","management":"example.com:80"}')
            with patch.object(installer, 'run') as command:
                with self.assertRaises(RuntimeError):
                    installer.gateway_request(profile, '/desktop/shutdown', 'POST')
                command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
