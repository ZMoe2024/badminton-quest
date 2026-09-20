import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation.browser_login import BrowserLogin, LoginCancelled, collect_credentials, app_url, LOGIN_URL
from badminton_reservation import booking_profile as profile
from badminton_reservation.gui_server import Application
from badminton_reservation import gui_server
from badminton_reservation.automation import Scheduler, account_key


def encoded(data):
    return base64.b64encode(json.dumps(data).encode()).decode()


def materials(username='test-user', expiry=9999999999):
    user = encoded({'username': username, 'userId': username + '-id'})
    token = 'header.' + base64.urlsafe_b64encode(json.dumps({'username': username, 'exp': expiry}).encode()).decode().rstrip('=') + '.signature'
    cookies = [{'name': 'synthetic-cookie', 'value': 'private-value', 'domain': 'resm.lzjtu.edu.cn', 'path': '/', 'httpOnly': True},
               {'name': 'TGC', 'value': 'private-sso', 'domain': 'authserver.lzjtu.edu.cn', 'path': '/authserver', 'httpOnly': True},
               {'name': 'unrelated', 'value': 'never-capture', 'domain': 'other.example', 'path': '/'}]
    return {'currentUser': user, 'userAgent': 'synthetic-agent'}, token, cookies


class CaptureTests(unittest.TestCase):
    def test_login_initializes_application_before_cas(self):
        url = urlsplit(LOGIN_URL)
        self.assertEqual(url.scheme, 'https')
        self.assertEqual(url.hostname, 'resm.lzjtu.edu.cn')
        self.assertEqual(url.path, '/')
        self.assertEqual(url.query, '')

    def test_http_only_cookies_and_current_identity(self):
        storage, token, cookies = materials()
        result = collect_credentials(storage, [token], cookies)
        self.assertEqual(result['token'], token)
        self.assertEqual(result['ssoCookies'][0]['path'], '/authserver')
        self.assertEqual(result['cookies'][0]['value'], 'private-value')
        self.assertNotIn('never-capture', json.dumps(result))

    def test_stale_or_other_account_tokens_never_match(self):
        storage, _, cookies = materials()
        for token in [materials('other')[1], materials(expiry=1)[1], 'broken', None]:
            self.assertIsNone(collect_credentials(storage, [token], cookies))
        self.assertIsNone(collect_credentials({}, [], cookies))

    def test_only_exact_https_application_origin(self):
        self.assertTrue(app_url('https://resm.lzjtu.edu.cn/#/home'))
        for url in ['http://resm.lzjtu.edu.cn', 'https://resm.lzjtu.edu.cn.evil.test',
                    'https://evil.test/resm.lzjtu.edu.cn', 'https://user@resm.lzjtu.edu.cn']:
            self.assertFalse(app_url(url))

    def test_cookie_token_fallback(self):
        storage, token, cookies = materials()
        cookies.append({'name': 'token', 'value': token, 'domain': 'resm.lzjtu.edu.cn', 'path': '/'})
        self.assertEqual(collect_credentials(storage, [], cookies)['token'], token)


class LoginCommitTests(unittest.TestCase):
    def setUp(self):
        self.credentials = collect_credentials(*((lambda m: (m[0], [m[1]], m[2]))(materials())))
        self.verify = Mock(return_value=(self.credentials, {'valid': True}))
        self.save = Mock()
        self.manager = BrowserLogin(threading.Lock(), self.verify, self.save)

    def test_success_is_verified_saved_and_redacted(self):
        self.manager._accept(self.credentials, time.monotonic()+5)
        self.verify.assert_called_once()
        self.save.assert_called_once()
        state = self.manager.snapshot()
        self.assertEqual(state['state'], 'success')
        for secret in ['private-value', 'private-sso', 'currentUser', self.credentials['token']]:
            self.assertNotIn(secret, json.dumps(state))

    def test_failed_verification_keeps_old_session(self):
        self.verify.side_effect = ValueError('rejected')
        with self.assertRaises(ValueError): self.manager._accept(self.credentials, time.monotonic()+5)
        self.save.assert_not_called()
        self.assertTrue(self.manager.network_lock.acquire(blocking=False))
        self.manager.network_lock.release()

    def test_cancel_during_verification_never_saves(self):
        def verify(value):
            self.manager.stop.set()
            return value, {'valid': True}
        self.verify.side_effect = verify
        with self.assertRaises(LoginCancelled): self.manager._accept(self.credentials, time.monotonic()+5)
        self.save.assert_not_called()

    def test_changed_identity_never_saves(self):
        changed = dict(self.credentials, currentUser=materials('different')[0]['currentUser'])
        self.verify.return_value = (changed, {'valid': True})
        with self.assertRaises(ValueError): self.manager._accept(self.credentials, time.monotonic()+5)
        self.save.assert_not_called()

    def test_page_closed_after_verification_never_saves(self):
        with self.assertRaises(LoginCancelled):
            self.manager._accept(self.credentials, time.monotonic()+5, Mock(side_effect=LoginCancelled))
        self.save.assert_not_called()

    def test_start_is_single_worker_and_cancel_preserves_success(self):
        self.manager.thread = Mock()
        self.manager.thread.is_alive.return_value = True
        self.manager._status('success', 'saved')
        with patch('badminton_reservation.browser_login.threading.Thread') as factory:
            self.manager.start()
            factory.assert_not_called()
        self.assertEqual(self.manager.cancel()['state'], 'success')

    def test_other_active_account_blocks_save(self):
        with tempfile.TemporaryDirectory() as temp:
            scheduler = Scheduler(threading.Lock(), Path(temp)/'tasks.json')
            scheduler.jobs['test'] = {'state': 'waiting', 'accountKey': account_key(self.credentials)}
            scheduler.assert_session_compatible(self.credentials)
            other = dict(self.credentials, currentUser=materials('other')[0]['currentUser'])
            with self.assertRaises(ValueError): scheduler.assert_session_compatible(other)
            scheduler.jobs['test']['state'] = 'cancelled'
            scheduler.assert_session_compatible(other)

    def test_import_failure_does_not_replace_session(self):
        app = Application()
        with patch.object(gui_server, 'authenticate', side_effect=ValueError('invalid')), patch.object(gui_server.session_store, 'save') as save:
            with self.assertRaises(ValueError): app.action({'action': 'import', 'credentials': {}})
            save.assert_not_called()


class ContactTests(unittest.TestCase):
    def test_phone_edit_preserves_other_fields_and_missing_phone_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp)/'booking.json'
            file.write_text(json.dumps({'occupyType': '1', 'formManagePropertyValueList': [
                {'propertyColumnCode': 'LXDH', 'propertyValue': ''}, {'propertyColumnCode': 'OTHER', 'propertyValue': 'keep'}]}))
            with patch.object(profile, 'PATH', file):
                with self.assertRaises(ValueError): profile.require_phone()
                profile.save_phone('13800000000')
                self.assertEqual(profile.load_phone(), '13800000000')
                profile.require_phone()
                self.assertEqual(json.loads(file.read_text())['formManagePropertyValueList'][1]['propertyValue'], 'keep')
                for value in ['', None, '<script>', '123']:
                    with self.assertRaises(ValueError): profile.save_phone(value)


if __name__ == '__main__': unittest.main()
