from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from smd_app.desktop_server import acquire_data_lock, seed_bundled_runtime
from smd_app.runtime import ASSETS, RUNTIME_VERSION, _platform_key


class DesktopLifecycleTests(unittest.TestCase):
    def test_bundled_runtime_preserves_existing_engine_and_never_copies_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundle = base / 'public-engine'
            bundle.mkdir()
            (bundle / 'ollama').write_text('public-test-binary')
            (bundle / 'llama-server').write_text('public-test-helper')
            receipt = {'version': RUNTIME_VERSION, 'asset': ASSETS[_platform_key()][0], 'sha256': ASSETS[_platform_key()][1]}
            (bundle / 'runtime.json').write_text(json.dumps(receipt))
            data_dir = base / 'user-data'
            self.assertTrue(seed_bundled_runtime(data_dir, bundle))
            destination = data_dir / 'runtimes' / 'ollama' / ('v' + RUNTIME_VERSION) / _platform_key()
            (destination / 'ollama').write_text('existing-engine')
            self.assertFalse(seed_bundled_runtime(data_dir, bundle))
            self.assertEqual((destination / 'ollama').read_text(), 'existing-engine')
            self.assertFalse((data_dir / 'runtime-state.json').exists())
            self.assertFalse((data_dir / 'models').exists())

    def test_external_bundle_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundle = base / 'engine'
            bundle.mkdir()
            receipt = {'version': RUNTIME_VERSION, 'asset': ASSETS[_platform_key()][0], 'sha256': ASSETS[_platform_key()][1]}
            (bundle / 'runtime.json').write_text(json.dumps(receipt))
            (bundle / 'ollama').write_text('test')
            (bundle / 'llama-server').symlink_to(base / 'outside')
            (base / 'outside').write_text('test')
            with self.assertRaisesRegex(ValueError, 'external link'):
                seed_bundled_runtime(base / 'data', bundle)

    def test_data_directory_lock_rejects_another_desktop(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with acquire_data_lock(directory):
                with self.assertRaisesRegex(RuntimeError, 'Another desktop'):
                    acquire_data_lock(directory)
            with acquire_data_lock(directory):
                if os.name == 'posix':
                    self.assertEqual((directory / 'desktop.lock').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
