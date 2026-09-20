import json
from pathlib import Path
import secrets
import tempfile
import unittest
import sys
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
try:
    from badminton_reservation.web_accounts import Accounts
    from badminton_reservation.web_workers import Workers
    AVAILABLE=True
except ImportError:
    AVAILABLE=False


@unittest.skipUnless(AVAILABLE,'Install requirements-web.txt to test the web workers')
class WorkerIsolationTests(unittest.TestCase):
    def test_school_login_window_is_exclusive_across_accounts(self):
        with tempfile.TemporaryDirectory() as folder:
            accounts=Accounts(Path(folder)/'accounts.sqlite3')
            pool=Workers(folder,secrets.token_bytes(32),accounts)
            calls=[]
            def rpc(uid, action):
                calls.append((uid,action['action']))
                return 200,{'active':True}
            with patch.object(pool,'_call',side_effect=rpc):
                self.assertEqual(pool.call('alice',{'action':'login-start'})[0],200)
                self.assertEqual(pool.call('bob',{'action':'login-start'})[0],409)
                self.assertNotIn(('bob','login-start'),calls)
                self.assertEqual(pool.call('bob',{'action':'orders'})[0],200)
            with patch.object(pool,'_call',side_effect=[(200,{'active':False}),(200,{'active':True})]):
                self.assertEqual(pool.call('bob',{'action':'login-start'})[0],200)
            self.assertEqual(pool.login_owner,'bob')

    def test_concurrent_real_processes_keep_profiles_and_orders_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);accounts=Accounts(root/'accounts.sqlite3')
            a=accounts.register('alpha','long-test-password')
            b=accounts.register('bravo','long-test-password')
            pool=Workers(root,secrets.token_bytes(32),accounts)
            try:
                with ThreadPoolExecutor(2) as threads:
                    results=list(threads.map(lambda uid:pool.call(uid),(a,b)))
                self.assertEqual([r[0] for r in results],[200,200])
                self.assertFalse(any(r[1]['sessionStored'] for r in results))
                self.assertNotEqual(pool.get(a)['process'].pid,pool.get(b)['process'].pid)
                self.assertEqual(pool.call(a,{'action':'save-profile','phone':'13800000000'})[0],200)
                self.assertEqual(pool.call(a,{'action':'profile'})[1]['phone'],'13800000000')
                self.assertEqual(pool.call(b,{'action':'profile'})[1]['phone'],'')
                path=root/'users'/a/'state/orders';path.mkdir(parents=True,exist_ok=True)
                (path/('a'*64+'.json')).write_text(json.dumps(dict(feeOrderId='synthetic-order',occupyId='synthetic-occupy',infoId='synthetic-court',expectedAmount='20',start='10:00',end='12:00')))
                self.assertEqual(len(pool.call(a,{'action':'orders'})[1]['orders']),1)
                self.assertEqual(pool.call(b,{'action':'orders'})[1]['orders'],[])
                cfg={'mode':'scheduled_watch','candidates':['主馆羽毛球场11'],'date':'2099-01-01','start':'10:00','end':'12:00',
                     'runAt':'2098-12-31T07:00:00','until':'2099-01-01T09:00:00','interval':30,'pay':False}
                status,value=pool.call(a,{'action':'task-save','config':cfg})
                self.assertEqual(status,200,value)
                self.assertEqual(len(pool.call(a,{'action':'tasks'})[1]['jobs']),1)
                self.assertEqual(pool.call(b,{'action':'tasks'})[1]['jobs'],[])
                self.assertEqual(pool.call(b,{'action':'task-cancel','id':value['id']})[0],400)
                self.assertEqual(pool.call(a,{'action':'tasks'})[1]['jobs'][0]['state'],'draft')
            finally:pool.close()
            # Re-open the worker without logging into school; persisted drafts survive.
            reopened=Workers(root,secrets.token_bytes(32),accounts)
            try:self.assertEqual(len(reopened.call(a,{'action':'tasks'})[1]['jobs']),1)
            finally:reopened.close()


if __name__=='__main__':unittest.main()
