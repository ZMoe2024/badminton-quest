import base64
import json
import time
import unittest
from badminton_reservation.web_credentials import prepare_credentials


def credentials(username='demo-school'):
    user = {'username': username, 'userId': 'demo-id'}
    payload = base64.urlsafe_b64encode(json.dumps({'username': username, 'exp': time.time()+600}).encode()).decode().rstrip('=')
    return {'cookie': 'site_session=example', 'token': 'header.'+payload+'.signature', 'currentUser': user}


class ImportTests(unittest.TestCase):
    def test_header_input_and_current_user_cookie(self):
        data = credentials()
        user = base64.b64encode(json.dumps(data.pop('currentUser')).encode()).decode()
        data['cookie'] = 'Cookie: '+data['cookie']+'; currentUser='+user+'; token='+data.pop('token')
        result = prepare_credentials(data)
        self.assertEqual(json.loads(base64.b64decode(result['currentUser']))['username'], 'demo-school')
        self.assertEqual(result['cookies'][0]['domain'], 'resm.lzjtu.edu.cn')
        self.assertNotIn('cookie', result)

    def test_mismatch_expiry_and_missing_identity_rejected(self):
        for change in [{'currentUser': {}}, {'currentUser': {'username': 'other', 'userId': 'other'}},
                       {'token': 'not-a-token'}, {'token': 'h.eyJleHAiOjEsInVzZXJuYW1lIjoiZGVtby1zY2hvb2wifQ.s'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_credentials(dict(credentials(), **change))

    def test_invalid_cookie_domains_and_header_injection_rejected(self):
        for change in [{'cookies': [{'name': 'session', 'value': 'secret', 'domain': 'evil.test'}]},
                       {'cookie': 'secret\r\nOther: header'}, {'ssoCookies': 'not-a-list'},
                       {'userAgent': ['wrong']}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_credentials(dict(credentials(), **change))


if __name__ == '__main__': unittest.main()
