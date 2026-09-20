import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from badminton_reservation.web_server import create_app


class AnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.workers=Mock()
        self.app=create_app(self.temp.name,'https://quest.test',workers=self.workers)
        self.accounts=self.app.extensions['quest_accounts']
        self.notices=self.app.extensions['quest_notices']
        self.admin=self.accounts.register('admin-test','long-test-password')
        self.user=self.accounts.register('reader-test','long-test-password')
        self.notices.grant('admin-test')
        self.client=self.app.test_client()
        self.body=dict(title='公告',body='正文 <script>alert(1)</script>',pinned=False,active=True)

    def login(self,uid):
        token=self.accounts.issue(uid)
        self.client.set_cookie('quest_session',token,domain='quest.test')
        return self.accounts.session(token)['csrf']

    def post(self,body,csrf):
        return self.client.post('/api/notices',json=body,base_url='https://quest.test',headers={'Origin':'https://quest.test','X-Local-Token':csrf})

    def test_server_denies_non_admin_and_csrf(self):
        csrf=self.login(self.user)
        self.assertEqual(self.post(dict(self.body,canManage=True,admin=True),csrf).status_code,403)
        with self.assertRaises(PermissionError):self.notices.save(self.user,self.body)
        csrf=self.login(self.admin)
        self.assertEqual(self.post(self.body,'bad').status_code,403)
        self.assertEqual(self.post(self.body,csrf).status_code,200)
        self.workers.call.assert_not_called()

    def test_drafts_unpublished_not_exposed_and_no_author_identifiers(self):
        oid=self.notices.save(self.admin,dict(self.body,active=False))
        self.assertEqual(self.notices.snapshot(self.user)['items'],[])
        self.notices.save(self.admin,dict(self.body,id=oid,version=1))
        view=self.notices.snapshot(self.user)
        self.assertEqual(len(view['items']),1)
        self.assertNotIn('author',view['items'][0]);self.assertNotIn('version',view['items'][0])
        self.assertFalse(view['canManage'])
        self.notices.save(self.admin,dict(self.body,id=oid,version=2,active=False))
        self.assertEqual(self.notices.snapshot(self.user)['items'],[])

    def test_pinned_first_and_concurrent_edits_do_not_overwrite(self):
        pinned=self.notices.save(self.admin,dict(self.body,pinned=True))
        self.notices.save(self.admin,self.body)
        self.assertEqual(self.notices.snapshot(self.user)['items'][0]['id'],pinned)
        self.notices.save(self.admin,dict(self.body,id=pinned,version=1,title='新版'))
        with self.assertRaises(ValueError):self.notices.save(self.admin,dict(self.body,id=pinned,version=1,title='旧版覆盖'))
        self.assertEqual(next(r for r in self.notices.snapshot(self.admin)['items'] if r['id']==pinned)['title'],'新版')

    def test_validation_and_admin_grant_requires_existing_user(self):
        with self.assertRaises(ValueError):self.notices.grant('missing-user')
        for changes in ({'title':''},{'title':'x'*81},{'body':'x'*4001},{'active':'yes'},{'pinned':1}):
            with self.assertRaises(ValueError):self.notices.save(self.admin,dict(self.body,**changes))

    def test_webp_variant_and_cache_varies(self):
        for name in ('gym','concept'):
            raw=self.client.get('/assets/'+name+'.png',base_url='https://quest.test',headers={'Accept':'image/png'})
            webp=self.client.get('/assets/'+name+'.png',base_url='https://quest.test',headers={'Accept':'image/webp'})
            self.assertEqual(webp.content_type,'image/webp')
            self.assertIn('Accept',webp.headers['Vary'])
            self.assertLess(len(webp.data),len(raw.data))
            self.assertEqual(webp.data[:4],b'RIFF')
            cached=self.client.get('/assets/'+name+'.png',base_url='https://quest.test',headers={'Accept':'image/webp','If-None-Match':webp.headers['ETag']})
            self.assertEqual(cached.status_code,304)
            self.assertNotEqual(raw.headers['ETag'],webp.headers['ETag'])
            raw.close();webp.close();cached.close()


if __name__=='__main__':unittest.main()
