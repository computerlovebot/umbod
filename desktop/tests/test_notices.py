import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/dependency-notices.py'
spec = importlib.util.spec_from_file_location('notices', SCRIPT)
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


class NoticeTests(unittest.TestCase):
    def test_pinned_supplements_match_reviewed_checksums(self):
        for key in json.loads((notices.SUPPLEMENTS / 'sources.json').read_text()):
            self.assertTrue(notices.supplement(key)[0][1])

    def test_unknown_version_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'Missing dependency notice'):
            notices.supplement('unknown-version')

    def test_modified_notice_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'LICENSE').write_text('modified')
            (root / 'sources.json').write_text(json.dumps({'fixture': {'file': 'LICENSE', 'notice_sha256': 'wrong'}}))
            with patch.object(notices, 'SUPPLEMENTS', root):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    notices.supplement('fixture')

    def test_dotnet_requires_both_license_and_third_party_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Umbod.Windows.deps.json').write_text(json.dumps({'libraries': {'runtimepack.Microsoft.NETCore.App.Runtime.win-x64/8.0.0': {}}}))
            pack = root / 'packages/microsoft.netcore.app.runtime.win-x64/8.0.0'
            pack.mkdir(parents=True)
            (pack / 'LICENSE.txt').write_text('fixture license')
            with self.assertRaisesRegex(ValueError, 'ThirdPartyNotices'):
                list(notices.dotnet_entries(root, root / 'packages'))
            (pack / 'ThirdPartyNotices.txt').write_text('fixture notices')
            self.assertEqual(len(list(notices.dotnet_entries(root, root / 'packages'))), 1)

    def test_notice_names_include_british_spelling_and_exclude_python_modules(self):
        self.assertTrue(notices.is_notice(Path('LICENCE.md')))
        self.assertTrue(notices.is_notice(Path('COPYING')))
        self.assertFalse(notices.is_notice(Path('licenses.py')))
