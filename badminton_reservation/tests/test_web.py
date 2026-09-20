import base64
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
try:
    from badminton_reservation.web_server import create_app
    from badminton_reservation.web_accounts import Accounts
    WEB_AVAILABLE=True
except ImportError:
    WEB_AVAILABLE=False


class FakeWorkers:
    def __init__(self): self.calls=[]
    def call(self,uid,action=None):
        self.calls.append((uid,action))
        return 200,{'courts':[], 'owner':uid} if action is None else {'owner':uid}


@unittest.skipUnless(WEB_AVAILABLE,'Install requirements-web.txt to run server tests')
class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.workers=FakeWorkers()
        self.app=create_app(self.temp.name,'https://quest.test',workers=self.workers)
        self.app.testing=True
        self.accounts=self.app.extensions['quest_accounts']
        self.a=self.app.test_client();self.b=self.app.test_client()

    def post(self,client,path,body,csrf=None,origin='https://quest.test'):
        return client.post(path,json=body,base_url='https://quest.test',headers={'Origin':origin,'X-Local-Token':csrf or ''})

    def get(self,client,path):return client.get(path,base_url='https://quest.test')

    def register(self,client,name):
        r=self.post(client,'/auth/register',{'username':name,'password':'test-password-long'})
        self.assertEqual(r.status_code,200)
        self.assertIn('HttpOnly',r.headers['Set-Cookie']);self.assertIn('Secure',r.headers['Set-Cookie'])
        return re.search(r'name="local-token" content="([^"]+)"',self.get(client,'/').text)[1]

    def test_unauthenticated_requests_and_private_paths(self):
        self.assertEqual(self.get(self.a,'/api/bootstrap').status_code,401)
        for path in ['/config/session.dpapi','/.quest-data/master.key','/../web_accounts.py']:
            self.assertEqual(self.get(self.a,path).status_code,404)
        self.assertEqual(self.get(self.a,'/').status_code,302)

    def test_users_are_isolated_and_cannot_choose_owner(self):
        ca=self.register(self.a,'alice');cb=self.register(self.b,'bobby')
        a=self.get(self.a,'/api/bootstrap').json['owner'];b=self.get(self.b,'/api/bootstrap').json['owner']
        self.assertNotEqual(a,b)
        result=self.post(self.a,'/api/action',{'action':'orders','userId':b},ca)
        self.assertEqual(result.json['owner'],a)
        self.assertEqual(self.post(self.a,'/api/action',{'action':'orders'},cb).status_code,403)
        self.assertEqual(self.post(self.a,'/api/action',{'action':'orders'},ca,'https://evil.test').status_code,403)
        self.assertEqual(self.post(self.a,'/api/action',{'action':'import','credentials':{}},ca).status_code,200)
        self.assertEqual(self.workers.calls[-1][0],a)
        self.assertEqual(self.post(self.a,'/api/action',{'action':'login-start'},ca).status_code,400)

    def test_public_registration_rate_limit_logout_and_password_rotation(self):
        csrf=self.register(self.a,'alice')
        self.post(self.b,'/auth/login',{'username':'alice','password':'test-password-long'})
        r=self.post(self.a,'/api/password',{'old':'test-password-long','new':'replacement-password'},csrf)
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.get(self.a,'/api/bootstrap').status_code,401)
        self.assertEqual(self.get(self.b,'/api/bootstrap').status_code,401)
        self.assertEqual(self.post(self.a,'/auth/login',{'username':'alice','password':'replacement-password'}).status_code,200)
        csrf=re.search(r'name="local-token" content="([^"]+)"',self.get(self.a,'/').text)[1]
        self.assertEqual(self.post(self.a,'/api/logout',{},csrf).status_code,200)
        self.assertEqual(self.get(self.a,'/api/bootstrap').status_code,401)
        self.assertTrue(self.accounts.rate_limit('test',1));self.assertFalse(self.accounts.rate_limit('test',1))

    def test_school_identity_unique_and_transactional(self):
        self.register(self.a,'alice');self.register(self.b,'bobby')
        a,b=self.accounts.ids()
        with self.accounts.school_binding(a,'school-a'):pass
        with self.assertRaises(ValueError):
            with self.accounts.school_binding(b,'school-a'):pass
        with self.assertRaises(ValueError):
            with self.accounts.school_binding(a,'school-b'):pass
        with self.assertRaises(RuntimeError):
            with self.accounts.school_binding(b,'school-b'):raise RuntimeError('failed save')
        with self.accounts.school_binding(b,'school-c'):pass

    def test_replay_survives_restart_and_is_scoped_per_user(self):
        self.accounts.claim_request('a','request-0001')
        reopened=Accounts(self.accounts.path)
        with self.assertRaises(ValueError):reopened.claim_request('a','request-0001')
        reopened.claim_request('b','request-0001')

    def test_wrong_host_and_missing_master_key_fail_closed(self):
        probe=self.a.get('/healthz',base_url='http://healthcheck.railway.app')
        self.assertEqual(probe.status_code,200)
        self.assertEqual(probe.json['status'],'ok')
        self.assertEqual(self.a.get('/api/bootstrap',base_url='http://healthcheck.railway.app').status_code,400)
        self.assertEqual(self.a.get('/login',base_url='https://evil.test').status_code,400)
        (Path(self.temp.name)/'master.key').unlink()
        with self.assertRaises(ValueError):create_app(self.temp.name,'https://quest.test',workers=self.workers)

    def test_credentials_encrypted_and_not_interchangeable(self):
        from badminton_reservation import session_store
        path=Path(self.temp.name)/'user-session'
        key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        with patch.dict(os.environ,{'BADMINTON_SERVER_KEY':key}):
            session_store.save(path,{'token':'private-test-secret'})
            self.assertNotIn(b'private-test-secret',path.read_bytes())
            self.assertEqual(session_store.load(path)['token'],'private-test-secret')
        with patch.dict(os.environ,{'BADMINTON_SERVER_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}):
            with self.assertRaises(ValueError):session_store.load(path)


if __name__=='__main__':unittest.main()
