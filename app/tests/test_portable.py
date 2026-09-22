import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_support import data_directory, InstanceLock, existing_address


class PortableTests(unittest.TestCase):
    def test_portable_and_installed_data_are_separate(self):
        with tempfile.TemporaryDirectory(prefix='MusicPro_') as temp:
            # macOS hands out /var/... for a /private/var temp dir; the app resolves.
            base = Path(temp).resolve()
            root = base/'Sinov papka — Ўзбек'
            app = root/'app'
            app.mkdir(parents=True)
            (root/'bundle.json').write_text('{}')
            installed = (Path.home()/'Library/Application Support/MusicProStudio/data'
                         if sys.platform == 'darwin' else base/'profile/MusicProStudio/data')
            with patch.dict(os.environ, {'LOCALAPPDATA':str(base/'profile')}, clear=True):
                self.assertEqual(data_directory(app), root/'data')
                (root/'installed.flag').write_text('installed')
                self.assertEqual(data_directory(app), installed)
                os.environ['MUSICPRO_DATA_DIR'] = str(base/'test-data')
                self.assertEqual(data_directory(app), base/'test-data')

    def test_second_process_cannot_edit_locked_queue_then_can_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            guard = InstanceLock(folder)
            code = ('from pathlib import Path; from runtime_support import InstanceLock; '
                    'import sys; g=InstanceLock(Path(sys.argv[1])); '
                    'print(g.acquire()); g.close()')
            try:
                self.assertTrue(guard.acquire())
                result = subprocess.run([sys.executable, '-c', code, temp], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'False')
            finally:
                # Release even on failure: Windows cannot delete a directory whose lock file is still open.
                guard.close()
            # Windows byte locks are mandatory, so the byte is readable only once released.
            # The rejected second process must not have rewritten it while it was held.
            self.assertEqual((folder/'instance.lock').read_bytes(), b'0')
            result = subprocess.run([sys.executable, '-c', code, temp], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), 'True', result.stderr)

    def test_existing_window_only_opens_loopback_musicpro_ports(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            for address in ['https://example.com', 'http://127.0.0.1:9000', 'file:///C:/Windows',
                            'http://127.0.0.1:8765/redirect', 'http://127.0.0.1:8785']:
                (p/'instance.json').write_text(json.dumps({'address':address}))
                self.assertIsNone(existing_address(p))
            for port in range(8765,8785):
                address = f'http://127.0.0.1:{port}'
                (p/'instance.json').write_text(json.dumps({'address':address}))
                self.assertEqual(existing_address(p), address)


if __name__ == '__main__':
    unittest.main()
