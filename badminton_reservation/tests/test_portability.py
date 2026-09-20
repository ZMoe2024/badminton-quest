"""Platform-independent storage contracts; real Keychain requires a Mac smoke test."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation import session_store as store


class PortableSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'config/session.keychain'
        self.secrets = {}
        self.backend = Mock()
        self.backend.get_password.side_effect = lambda service, identifier: self.secrets.get((service, identifier))
        self.backend.set_password.side_effect = lambda service, identifier, key: self.secrets.__setitem__((service, identifier), key)
        self.platform = patch.object(store, 'platform_name', return_value='darwin')
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.keychain = patch.object(store, 'mac_keychain', return_value=self.backend)
        self.keychain.start()
        self.addCleanup(self.keychain.stop)

    def test_roundtrip_and_renewal_reuse_key(self):
        original = {'token': 'synthetic-private-token', 'cookies': [{'name': 'x', 'value': 'synthetic-cookie'}]}
        store.save(self.path, original)
        self.assertEqual(store.load(self.path), original)
        self.assertNotIn(b'synthetic-private-token', self.path.read_bytes())
        first_id, _ = store.mac_parts(self.path.read_bytes())
        store.save(self.path, {'token': 'renewed'})
        self.assertEqual(store.load(self.path), {'token': 'renewed'})
        self.assertEqual(store.mac_parts(self.path.read_bytes())[0], first_id)
        self.backend.set_password.assert_called_once()
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_same_mac_move_keeps_key_reference(self):
        store.save(self.path, {'token': 'test'})
        moved = self.path.with_name('moved.keychain')
        self.path.rename(moved)
        self.assertEqual(store.load(moved), {'token': 'test'})

    def test_missing_key_fails_closed(self):
        store.save(self.path, {'token': 'test'})
        self.secrets.clear()
        with self.assertRaises(ValueError): store.load(self.path)
        self.assertEqual(self.secrets, {})

    def test_denied_keychain_does_not_write_plaintext(self):
        self.backend.get_password.side_effect = RuntimeError('denied')
        with self.assertRaises(ValueError): store.save(self.path, {'token': 'test'})
        self.assertFalse(self.path.exists())

    def test_tampering_rejected(self):
        store.save(self.path, {'token': 'test'})
        data = self.path.read_bytes()
        self.path.write_bytes(data[:-12] + b'broken-data=')
        with self.assertRaises(ValueError): store.load(self.path)

    def test_cross_platform_files_have_clear_error(self):
        self.path.parent.mkdir()
        self.path.write_bytes(store.MAGIC + b'fake-windows-data')
        with self.assertRaisesRegex(ValueError, 'Windows'):
            store.load(self.path)
        store.save(self.path, {'token': 'test'})
        with patch.object(store, 'platform_name', return_value='win32'):
            with self.assertRaisesRegex(ValueError, 'macOS'):
                store.load(self.path)

    def test_failed_replace_preserves_previous_session(self):
        store.save(self.path, {'token': 'previous'})
        with patch.object(store.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): store.save(self.path, {'token': 'next'})
        self.assertEqual(store.load(self.path), {'token': 'previous'})
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
