import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from badminton_reservation.web_accounts import Accounts
from badminton_reservation.web_rentals import Rentals, court_catalog, TZ, money
from badminton_reservation.web_server import create_app
from badminton_reservation import rental_worker as worker


class RentalFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.accounts = Accounts(Path(self.temp.name)/'accounts.sqlite3')
        self.owner = self.accounts.register('owner-private', 'long-test-password')
        self.renter = self.accounts.register('renter', 'long-test-password')
        self.other = self.accounts.register('outsider', 'long-test-password')
        with self.accounts.school_binding(self.owner, hashlib.sha256(b'school-private').hexdigest()): pass
        self.store = Rentals(self.accounts)
        self.court = court_catalog()[0]['id']
        self.config = {'venue': self.court, 'date': (dt.datetime.now(TZ).date()+dt.timedelta(days=1)).isoformat(), 'start':'10:00', 'end':'12:00'}
        self.offer_data = {'fee':'5', 'maxAmount':'50', 'uses':1, 'hours':24, 'courts':[self.court], 'authorized':True}
        self.offer = self.store.publish(self.owner, self.offer_data)

    def order(self, **extra):
        body = dict(offerId=self.offer, config=self.config, fee='5', requestId='request-0001', confirmed=True)
        body.update(extra)
        return self.store.request(self.renter, body)


class AuthorizationTests(RentalFixture):
    def test_renter_needs_no_school_identity_and_views_are_allowlists(self):
        offers = self.store.snapshot(self.renter)['offers']
        self.assertEqual(len(offers),1)
        self.assertNotIn('remaining',offers[0]);self.assertNotIn('maxAmount',offers[0])
        self.assertNotIn(self.owner,json.dumps(offers))
        oid = self.order()
        hidden = {'feeOrderId':'secret-school-order','occupyId':'secret-reservation','phone':'138PRIVATE','userName':'private-student'}
        self.store.change(oid, self.owner, 'unpaid', amount='40.00', order=hidden)
        view = self.store.snapshot(self.renter)
        wire = json.dumps(view)
        for secret in [self.owner, self.other, 'owner-private','school-private',*hidden.values()]:
            self.assertNotIn(secret, wire)
        self.assertNotIn('maxAmount',view['orders'][0])
        self.assertEqual(view['orders'][0]['fee'],'5.00')
        self.assertEqual(view['orders'][0]['role'],'renter')
        self.assertEqual(self.store.snapshot(self.other)['orders'],[])
        self.assertEqual(self.store.snapshot(self.owner)['orders'][0]['maxAmount'],'50.00')

    def test_concurrent_claims_cannot_exceed_authorized_count(self):
        def attempt(i):
            try: return self.order(requestId='request-'+str(i).zfill(8),config=dict(self.config,start=f'{8+i:02}:00',end=f'{9+i:02}:00'))
            except ValueError: return None
        with ThreadPoolExecutor(8) as pool: ids=list(pool.map(attempt,range(8)))
        self.assertEqual(len([x for x in ids if x]),1)
        self.assertEqual(self.store.snapshot(self.owner)['mine'][0]['remaining'],0)

    def test_replay_after_restart_returns_original_without_new_charge(self):
        oid = self.order()
        reopened = Rentals(self.accounts)
        self.assertEqual(reopened.request(self.renter,dict(offerId=self.offer,config=self.config,fee='5',requestId='request-0001',confirmed=True)),oid)
        self.assertEqual(len(reopened.snapshot(self.renter)['orders']),1)

    def test_revoke_stops_new_orders_but_preserves_already_accepted_authorization(self):
        self.store.revoke(self.owner,self.offer)
        with self.assertRaises(ValueError):self.order()
        self.offer=self.store.publish(self.owner,self.offer_data)
        oid=self.order()
        self.store.revoke(self.owner,self.offer)
        self.assertIsNotNone(self.store.begin(oid,self.owner))
        self.assertIsNone(self.store.begin(oid,self.owner))

    def test_permission_and_scope_fail_closed(self):
        with self.assertRaises(ValueError):self.store.revoke(self.renter,self.offer)
        with self.assertRaises(ValueError):self.store.publish(self.renter,self.offer_data)
        for changes in [{'confirmed':False},{'fee':'6'},{'config':dict(self.config,venue='foreign-court')},
                        {'config':dict(self.config,date='1999-01-01')},{'config':dict(self.config,start='18:00',end='08:00')}]:
            with self.assertRaises(ValueError):self.order(**changes)
        oid=self.order()
        self.assertIsNone(self.store.begin(oid,self.renter))
        with self.assertRaises(ValueError):self.store.get(oid,self.other)

    def test_invalid_authorization_money_and_expiry(self):
        for value in ('NaN','Infinity','-1','0.001','10001',None,True):
            with self.assertRaises(ValueError):money(value)
        for changes in [{'authorized':False},{'uses':0},{'uses':True},{'hours':169},{'maxAmount':'0'},{'courts':[]}]:
            with self.assertRaises(ValueError):self.store.publish(self.owner,dict(self.offer_data,**changes))
        with self.accounts.connect() as db:db.execute('UPDATE rental_offers SET expires=0')
        with self.assertRaises(ValueError):self.order()

    def test_different_request_id_and_other_offer_cannot_duplicate_same_slot(self):
        self.order()
        second=self.store.publish(self.owner,self.offer_data)
        with self.assertRaises(ValueError):self.order(offerId=second,requestId='request-0002')


class ExecutionTests(RentalFixture):
    def setUp(self):
        super().setUp()
        self.oid=self.order()
        self.app=SimpleNamespace(scheduler=Mock())
        self.school_order={'feeOrderId':'private-fee-id','occupyId':'private-occupy-id','infoId':self.court,
                           'expectedAmount':'40.00','start':self.config['date']+' 10:00:00','end':self.config['date']+' 12:00:00'}
        self.result={'submission':{'outcome':'success','reservation':{'code':'2'},'message':'secret phone student'},
                     'order':{'configuration':self.school_order}}
        self.book=self.patch('book',return_value=self.result)
        self.pay=self.patch('pay',return_value={'outcome':'accepted','message':'private-balance'})
        self.patch('require_phone')
        self.patch('authenticate',return_value=({'token':'private-token'},{}))
        self.patch('expected_identity',return_value=('school-private','private-user-id'))
        self.patch('resolve',return_value=({'infoId':self.court},self.config['date'],'10:00','12:00'))
        self.live=self.patch('fetch_availability',return_value={'courts':[{'slots':[{'start':'10:00','end':'12:00','available':True}]}]})
        self.client=self.patch('ResourceAPI').return_value
        self.client.query.return_value={'feeOrderId':'private-fee-id','userName':'school-private',
            'recordTimeStart':self.school_order['start'],'recordTimeEnd':self.school_order['end'],
            'feeOrderAmount':'40.00','feePayStatus':'1'}

    def patch(self,name,**kw):
        p=patch.object(worker.gui,name,**kw);r=p.start();self.addCleanup(p.stop);return r

    def run_order(self):worker.execute(self.store,self.owner,self.app,self.oid)
    def state(self):return self.store.public_order(self.oid,self.renter)['state']

    def test_happy_path_one_booking_one_payment_final_verification(self):
        self.run_order();self.run_order()
        self.assertEqual(self.state(),'paid')
        self.book.assert_called_once();self.pay.assert_called_once()
        self.assertFalse(self.book.call_args.kwargs['pay_after'])
        self.assertEqual(self.pay.call_args.args[1]['expectedAmount'],'40.00')
        wire=json.dumps(self.store.snapshot(self.renter))
        for private in ['private-token','private-balance','private-fee-id','private-user-id','secret phone student']:
            self.assertNotIn(private,wire)

    def test_concurrent_execution_claims_only_once(self):
        with ThreadPoolExecutor(4) as pool:list(pool.map(lambda _:self.run_order(),range(4)))
        self.book.assert_called_once();self.pay.assert_called_once()
        self.assertEqual(self.state(),'paid')

    def test_over_cap_never_pays_or_rebooks(self):
        self.school_order['expectedAmount']='50.01'
        self.run_order();self.run_order()
        self.assertEqual(self.state(),'over_limit');self.pay.assert_not_called();self.book.assert_called_once()

    def test_payment_accepted_is_not_confirmation(self):
        self.client.query.return_value['feePayStatus']='0'
        self.run_order();self.assertEqual(self.state(),'payment_pending')
        self.client.query.return_value['feePayStatus']='1'
        worker.reconcile(self.store,self.owner,self.app,self.oid)
        self.assertEqual(self.state(),'paid');self.pay.assert_called_once()

    def test_unmatched_identity_or_amount_cannot_confirm_paid(self):
        for key,value in [('userName','foreign'),('feeOrderAmount','99'),('feeOrderId','other')]:
            self.client.query.return_value[key]=value
        self.run_order();self.assertEqual(self.state(),'payment_pending')

    def test_booking_timeout_is_unknown_and_never_retried(self):
        self.book.side_effect=TimeoutError('private-token private-student')
        self.run_order();self.run_order()
        self.assertEqual(self.state(),'unknown');self.book.assert_called_once();self.pay.assert_not_called()

    def test_payment_exception_is_indeterminate_and_never_retried(self):
        self.pay.side_effect=TimeoutError('private-card-number')
        self.run_order();self.run_order()
        self.assertEqual(self.state(),'payment_pending');self.pay.assert_called_once()

    def test_no_free_slot_never_creates_booking(self):
        self.live.return_value['courts'][0]['slots'][0]['available']=False
        self.run_order();self.assertEqual(self.state(),'failed');self.book.assert_not_called();self.pay.assert_not_called()

    def test_wrong_school_identity_or_wrong_worker_never_creates_booking(self):
        worker.execute(self.store,self.renter,self.app,self.oid)
        self.assertEqual(self.state(),'queued')
        with patch.object(worker.gui,'expected_identity',return_value=('another-school','uid')):self.run_order()
        self.assertEqual(self.state(),'failed');self.book.assert_not_called()

    def test_no_charge_requested_does_not_pay(self):
        self.result['submission']['reservation']['code']='1'
        self.run_order();self.assertEqual(self.state(),'booked');self.pay.assert_not_called()

    def test_missing_order_does_not_guess_amount_or_pay(self):
        self.result.pop('order')
        self.run_order();self.assertEqual(self.state(),'unpaid');self.pay.assert_not_called()

    def test_insufficient_balance_does_not_leak_or_retry(self):
        self.pay.return_value={'outcome':'insufficient_balance','message':'private-owner balance 3.25'}
        self.client.query.return_value['feePayStatus']='0'
        self.run_order();self.run_order()
        self.assertEqual(self.state(),'unpaid');self.pay.assert_called_once()
        wire=json.dumps(self.store.snapshot(self.renter))
        self.assertNotIn('3.25',wire);self.assertNotIn('insufficient_balance',wire)

    def test_crash_after_claim_does_not_auto_retry(self):
        self.store.begin(self.oid,self.owner)
        self.store.change(self.oid,self.owner,'submitting')
        self.run_order();self.assertEqual(self.state(),'submitting');self.book.assert_not_called()

    def test_crash_during_payment_can_be_verified_without_resubmission(self):
        self.store.begin(self.oid,self.owner)
        self.store.change(self.oid,self.owner,'paying',amount='40.00',order=self.school_order)
        worker.reconcile(self.store,self.owner,self.app,self.oid)
        self.assertEqual(self.state(),'paid');self.pay.assert_not_called();self.book.assert_not_called()


class RentalRoutesTests(RentalFixture):
    def setUp(self):
        super().setUp()
        # create_app deliberately refuses to silently replace a missing key on an existing DB.
        import base64
        (Path(self.temp.name)/'master.key').write_text(base64.urlsafe_b64encode(b'x'*32).decode())
        self.workers=Mock()
        self.workers.call.return_value=(200,{'ready':True, 'slots':[{'start':'10:00','end':'12:00','available':True,'userName':'private-owner'}], 'private':'NEVER_RETURN_THIS'})
        self.app=create_app(self.temp.name,'https://quest.test',workers=self.workers)
        self.app.testing=True;self.client=self.app.test_client()
        token=self.accounts.issue(self.renter)
        self.client.set_cookie('quest_session',token,domain='quest.test')
        self.csrf=self.accounts.session(token)['csrf']

    def post(self,action,data,csrf=None):
        return self.client.post('/api/rentals/'+action,json=data,base_url='https://quest.test',headers={'Origin':'https://quest.test','X-Local-Token':csrf if csrf is not None else self.csrf})

    def test_server_resolves_owner_and_rejects_arbitrary_worker_access(self):
        response=self.post('request',dict(offerId=self.offer,config=self.config,fee='5',confirmed=True,requestId='rental-request-01',owner=self.other))
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.workers.call.call_args.args[0],self.owner)
        self.assertNotIn('NEVER_RETURN_THIS',response.text)
        self.assertNotIn(self.owner,response.text)
        result=self.client.post('/api/action',json={'action':'rental-run','id':response.json['order']['id']},base_url='https://quest.test',headers={'Origin':'https://quest.test','X-Local-Token':self.csrf})
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.post('run',{'id':'a'*24}).status_code,400)
        self.assertEqual(self.post('run',{'id':response.json['order']['id']},csrf='bad').status_code,403)

    def test_slots_are_filtered_and_rpc_error_is_not_disclosed(self):
        data=dict(offerId=self.offer,venue=self.court,date=self.config['date'])
        response=self.post('slots',data)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json,{'slots':[{'start':'10:00','end':'12:00','available':True}]})
        self.workers.call.return_value=(400,{'error':'private-student private-phone private-cookie'})
        response=self.post('slots',data)
        self.assertEqual(response.status_code,400)
        self.assertNotIn('private-',response.text)

    def test_worker_timeout_keeps_existing_order_and_no_raw_data(self):
        self.workers.call.return_value=(503,{'error':'private-cookies'})
        result=self.post('request',dict(offerId=self.offer,config=self.config,fee='5',confirmed=True,requestId='rental-request-01'))
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['order']['state'],'queued')
        self.assertNotIn('private-cookies',result.text)


if __name__=='__main__':unittest.main()
