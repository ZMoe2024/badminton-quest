import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation import session, session_store


class SessionTests(unittest.TestCase):
    @patch.object(session, 'renew')
    @patch.object(session, 'probe')
    def test_valid_session_does_not_renew(self, probe, renew):
        probe.return_value = ({'ssoCookies': [1]}, True)
        _, result = session.ensure_session({})
        self.assertFalse(result['renewed'])
        renew.assert_not_called()

    @patch.object(session, 'renew')
    @patch.object(session, 'probe')
    def test_expired_session_renews_once_and_verifies(self, probe, renew):
        probe.side_effect = [({'old': True}, False), ({'new': True}, True)]
        renew.return_value = {'new': True}
        value, result = session.ensure_session({})
        self.assertTrue(result['renewed'])
        self.assertEqual(value, {'new': True})
        renew.assert_called_once_with({'old': True})

    @patch.object(session, 'renew')
    @patch.object(session, 'probe', side_effect=ValueError('network challenge'))
    def test_other_errors_do_not_trigger_login(self, probe, renew):
        with self.assertRaises(ValueError): session.ensure_session({})
        renew.assert_not_called()

    @patch.object(session.requests, 'Session')
    def test_cas_requires_ticket_and_stays_on_allowed_hosts(self, factory):
        http = factory.return_value
        for destination in [session.SERVICE, 'https://example.com/?ticket=secret',
                            'http://authserver.lzjtu.edu.cn/login?ticket=secret']:
            http.get.return_value = Mock(status_code=302, headers={'Location': destination})
            with self.assertRaises(session.LoginRequired):
                session.acquire_ticket({'ssoCookies': [{'name': 'TGC', 'value': 'test',
                    'domain': 'authserver.lzjtu.edu.cn', 'path': '/'}]})

    @patch.object(session.requests, 'Session')
    def test_cas_ticket_is_not_followed_to_service(self, factory):
        http = factory.return_value
        http.cookies = []
        http.get.return_value = Mock(status_code=302, headers={'Location': session.SERVICE + '?ticket=test-ticket'})
        ticket, _ = session.acquire_ticket({'ssoCookies': [
            {'name': 'ignored', 'value': 'test', 'domain': 'unrelated.invalid', 'path': '/'}]})
        self.assertEqual(ticket, 'test-ticket')
        http.get.assert_called_once()

    @patch.object(session, 'acquire_ticket', return_value=('test-ticket', []))
    @patch.object(session, 'ResourceAPI')
    @patch.object(session, 'expected_identity', return_value=('original-user', 'original-id'))
    def test_renewal_rejects_account_change(self, identity, api, acquire):
        api.return_value.get.return_value = Mock(status_code=200, text=json.dumps({
            'token': 'not-printed', 'sysUser': {'username': 'other', 'userId': 'other'}}))
        with self.assertRaises(session.LoginRequired): session.renew({})
        api.return_value.close.assert_called_once()

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_encrypted_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.dpapi'
            data = {'token': 'synthetic-secret-for-test'}
            session_store.save(path, data)
            self.assertNotIn(data['token'].encode(), path.read_bytes())
            self.assertEqual(session_store.load(path), data)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])


if __name__ == '__main__': unittest.main()
