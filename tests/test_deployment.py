"""Run with: python -m unittest discover -s tests -p test_deployment.py"""

import os
import stat
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from config.runtime import prepare_secret, secret_key, main


class DeploymentTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'geteuid'), 'Docker bootstrap is Linux-only')
    def test_mount_permissions_are_prepared_before_privilege_drop(self):
        module_path = Path(__file__).resolve().parents[1] / 'scripts' / 'container_start.py'
        spec = importlib.util.spec_from_file_location('container_start', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        events = []
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory) / 'storage'
            storage.mkdir()
            (storage / 'db.sqlite3').touch()
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(module.os, 'geteuid', return_value=0), \
                    patch.object(module.os, 'chown', side_effect=lambda *a, **kw: events.append('chown')), \
                    patch.object(module.os, 'setgroups', side_effect=lambda *a: events.append('groups')), \
                    patch.object(module.os, 'setgid', side_effect=lambda *a: events.append('gid')), \
                    patch.object(module.os, 'setuid', side_effect=lambda *a: events.append('uid')):
                module.prepare_storage(storage)
                module.drop_privileges()
        self.assertEqual(events, ['chown', 'chown', 'groups', 'gid', 'uid'])

    def test_key_survives_reinitialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'secret'
            with patch.dict(os.environ, {'DJANGO_SECRET_KEY_FILE': str(path)}, clear=True):
                prepare_secret()
                first = secret_key()
                prepare_secret()
                self.assertEqual(first, secret_key())
                self.assertGreaterEqual(len(first), 64)
                if os.name != 'nt':
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_environment_key_has_priority_and_creates_no_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'secret'
            with patch.dict(os.environ, {
                'DJANGO_SECRET_KEY': 'an-explicit-existing-key',
                'DJANGO_SECRET_KEY_FILE': str(path),
            }, clear=True):
                prepare_secret()
                self.assertEqual(secret_key(), 'an-explicit-existing-key')
                self.assertFalse(path.exists())

    def test_empty_saved_key_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'secret'
            path.write_text('')
            with patch.dict(os.environ, {'DJANGO_SECRET_KEY_FILE': str(path)}, clear=True):
                with self.assertRaisesRegex(RuntimeError, 'empty'):
                    prepare_secret()
                self.assertEqual(path.read_text(), '')

    def test_missing_production_key_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                secret_key()
            self.assertTrue(secret_key(debug=True).startswith('dev-only-'))

    def test_invalid_port_fails_before_creating_a_secret(self):
        for value in ['0', '65536', 'oops', '80;echo secret']:
            with self.subTest(port=value), patch.dict(os.environ, {'PORT': value}, clear=True):
                with self.assertRaisesRegex(RuntimeError, 'PORT'):
                    main()

    def test_does_not_print_the_secret(self):
        with patch.dict(os.environ, {'DJANGO_SECRET_KEY': 'never-log-this'}, clear=True):
            self.assertNotIn('never-log-this', prepare_secret())


if __name__ == '__main__':
    unittest.main()
