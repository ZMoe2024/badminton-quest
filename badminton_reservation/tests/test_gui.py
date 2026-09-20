import datetime as dt
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch, Mock
import requests
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation.availability import classify_slots, fetch_availability
from badminton_reservation.gui_server import Application, LocalServer, make_handler, read_order


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.groups = [{'infoId': 'court', 'minBlockNum': 1, 'maxBlockNum': 1,
            'resUseTimeBlockInfoList': [dict(blockStartTime=a, blockEndTime=b, rsrvShareType='1')
                for a,b in [('10:00','12:00'),('12:00','14:00'),('14:00','16:00')]]}]
        self.rules = {'subManageTimeConfigVo': {'useMaxTime': '{"day":3}',
                       'lastDayOpenTime': '07:00', 'isSubBeforeEndTime': '1'}}

    def classify(self, ranges=(), date='2026-09-19', now=None, **kw):
        return classify_slots(self.groups,self.rules,ranges,date,'court',
                              now=now or dt.datetime(2026,9,18,10),**kw)

    def test_half_open_occupancy_boundaries(self):
        rows=self.classify([(dt.datetime(2026,9,19,12),dt.datetime(2026,9,19,14),'已占用')])
        self.assertEqual([r['available'] for r in rows],[True,False,True])

    def test_partial_overlap_and_lock_never_marked_free(self):
        rows=self.classify([(dt.datetime(2026,9,19,11),dt.datetime(2026,9,19,13),'已锁定')])
        self.assertEqual([r['available'] for r in rows],[False,False,True])

    def test_past_late_opening_and_outside_horizon(self):
        self.assertFalse(any(r['available'] for r in self.classify(date='2026-09-21')))
        self.assertFalse(any(r['available'] for r in self.classify(date='2026-09-20',now=dt.datetime(2026,9,18,6))))
        self.assertFalse(any(r['available'] for r in self.classify(date='2026-09-17')))

    def test_end_time_expiry_and_forced_occupancy(self):
        rows=self.classify(date='2026-09-18',now=dt.datetime(2026,9,18,11))
        self.assertTrue(rows[0]['available'])
        self.assertFalse(any(r['available'] for r in self.classify(forced=True)))

    def test_query_failure_is_unknown_not_free(self):
        client=Mock();client.query.side_effect=[[],TimeoutError()]
        with patch('badminton_reservation.availability.ResourceAPI',return_value=client):
            result=fetch_availability({},[{'infoId':'court','name':'court'}],'2026-09-19')
        self.assertEqual(result['courts'][0]['slots'],[])
        self.assertIn('error',result['courts'][0])

    def test_parallel_courts_keep_order_isolate_clients_and_bound_concurrency(self):
        clients=[]
        barrier=threading.Barrier(3)
        lock=threading.Lock()
        def new_client(credentials):
            client=Mock();client.owner=None;client.query.return_value=['forced-court']
            with lock: clients.append(client)
            return client
        def court(client, row, date, forced):
            ident=threading.get_ident()
            if client.owner is None:
                client.owner=ident
                barrier.wait(timeout=3)
            self.assertEqual(client.owner, ident)
            self.assertEqual(forced, ['forced-court'])
            if row['infoId']=='court-4':raise ValueError('school unavailable')
            return dict(row,slots=[{'available':False}])
        rows=[{'infoId':f'court-{n}','name':str(n)} for n in range(10)]
        with patch('badminton_reservation.availability.ResourceAPI',side_effect=new_client), \
             patch('badminton_reservation.availability.fetch_court',side_effect=court):
            result=fetch_availability({},rows,'2026-09-19',max_workers=100)
        self.assertEqual(len(clients),3)
        self.assertEqual([r['infoId'] for r in result['courts']],[r['infoId'] for r in rows])
        self.assertEqual(result['courts'][4]['slots'],[])
        self.assertIn('error',result['courts'][4])
        self.assertEqual(len({c.owner for c in clients}),3)
        for client in clients:client.close.assert_called_once()

    def test_single_court_keeps_one_client_for_submission_checks(self):
        client=Mock();client.query.return_value=[]
        with patch('badminton_reservation.availability.ResourceAPI',return_value=client) as create, \
             patch('badminton_reservation.availability.fetch_court',return_value={'slots':[]}) as fetch:
            fetch_availability({},[{'infoId':'court','name':'court'}],'2026-09-19')
        create.assert_called_once()
        self.assertIs(fetch.call_args.args[0],client)
        client.close.assert_called_once()


class GUIBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=Application()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.app))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def test_bootstrap_does_not_expose_credentials(self):
        response=requests.get(self.url+'/api/bootstrap')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('token',response.json())
        self.assertNotIn('cookies',response.json())

    def test_local_server_cannot_replace_existing_listener(self):
        server = LocalServer(('127.0.0.1', 0), make_handler(Application()))
        try:
            with self.assertRaises(OSError):
                LocalServer(server.server_address, make_handler(Application()))
        finally:
            server.server_close()

    def test_filesystem_and_cross_origin_are_rejected(self):
        self.assertEqual(requests.get(self.url+'/config/session.dpapi').status_code,404)
        self.assertEqual(requests.get(self.url+'/',headers={'Host':'evil.invalid'}).status_code,403)
        with patch.object(self.app,'action') as action:
            r=requests.post(self.url+'/api/action',json={'action':'book'},
                headers={'Origin':'https://evil.invalid','X-Local-Token':self.app.token})
            self.assertEqual(r.status_code,403);action.assert_not_called()

    def test_action_requires_token_and_origin(self):
        with patch.object(self.app,'action',return_value={'ok':True}) as action:
            self.assertEqual(requests.post(self.url+'/api/action',json={'action':'book'}).status_code,403)
            r=requests.post(self.url+'/api/action',json={'action':'orders'},
                headers={'Origin':self.url,'X-Local-Token':self.app.token})
            self.assertEqual(r.json(),{'ok':True});action.assert_called_once()

    def test_confirmation_and_duplicate_submission(self):
        app=Application()
        with self.assertRaises(ValueError):app.confirm_once({'requestId':'request-123'})
        app.confirm_once({'confirmed':True,'requestId':'request-123'})
        with self.assertRaises(ValueError):app.confirm_once({'confirmed':True,'requestId':'request-123'})

    def test_order_file_traversal_rejected(self):
        with self.assertRaises(ValueError):read_order('../../config/session.dpapi')

    def test_login_launch_requires_local_origin_and_token(self):
        with patch.object(self.app.browser_login, 'start', return_value={'state': 'opening'}) as start:
            body = {'action': 'login-start'}
            self.assertEqual(requests.post(self.url+'/api/action', json=body).status_code, 403)
            self.assertEqual(requests.post(self.url+'/api/action', json=body,
                headers={'Origin':'https://evil.invalid','X-Local-Token':self.app.token}).status_code, 403)
            start.assert_not_called()
            response=requests.post(self.url+'/api/action', json=body,
                headers={'Origin':self.url,'X-Local-Token':self.app.token})
            self.assertEqual(response.json()['state'], 'opening')
            start.assert_called_once()

    def test_login_status_remains_available_during_network_verification(self):
        with self.app.lock:
            response=requests.post(self.url+'/api/action', json={'action':'login-status'},
                headers={'Origin':self.url,'X-Local-Token':self.app.token}, timeout=3)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('token', response.json())

if __name__=='__main__':unittest.main()
