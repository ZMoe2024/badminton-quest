import datetime as dt
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation import automation as a


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = dt.datetime(2026,9,18,10)
        self.clock = patch.object(a,'now_local',side_effect=lambda:self.now).start()
        self.identity = patch.object(a,'expected_identity',return_value=('account','user')).start()
        self.auth = patch.object(a,'authenticate',return_value=({'session':'secret'},{'renewed':False})).start()
        self.resolve = patch.object(a,'resolve',side_effect=lambda c:({'infoId':c['venue'],'name':c['venue']},c['date'],c['start'],c['end'])).start()
        self.fetch = patch.object(a,'fetch_availability',return_value=self.availability()).start()
        self.book = patch.object(a,'book',return_value=self.success()).start()
        self.pay = patch.object(a,'pay',return_value={'outcome':'insufficient_balance','message':'余额不足'}).start()
        self.addCleanup(patch.stopall)
        self.path = Path(self.tmp.name)/'tasks.json'
        self.s = a.Scheduler(threading.Lock(),self.path)

    def config(self,**kw):
        return dict(mode='watch',candidates=['court1','court2'],date='2026-09-19',start='10:00',end='12:00',
                    runAt='2026-09-18T10:10:00',until='2026-09-19T09:00:00',interval=30,pay=False,**kw)

    def job(self,cfg=None):
        j=self.s.save_draft(cfg or self.config());self.s.enable(j['id'],{})
        return self.s.jobs[j['id']]

    def availability(self,first=True,second=True):
        return {'courts':[{'infoId':name,'slots':[{'start':'10:00','end':'12:00','available':free}]} for name,free in [('court1',first),('court2',second)]]}

    def success(self,amount='40'):
        return {'submission':{'outcome':'success','reservation':{'occupyId':'r1'}},
                'order':{'configuration':{'infoId':'court1','occupyId':'r1','feeOrderId':'o1','expectedAmount':amount,'start':'2026-09-19 10:00:00','end':'2026-09-19 12:00:00'}}}

    def test_unopened_future_can_be_saved_without_network(self):
        self.s.save_draft(self.config())
        self.auth.assert_not_called();self.fetch.assert_not_called();self.book.assert_not_called()

    def test_scheduled_waits_then_submits_only_one_by_priority(self):
        c=self.config();c['mode']='scheduled_watch';j=self.job(c)
        self.s.tick();self.book.assert_not_called()
        self.now+=dt.timedelta(minutes=10);self.s.tick()
        self.assertEqual(j['state'],'booked');self.assertEqual(self.book.call_args.args[0]['venue'],'court1')
        self.s.tick();self.book.assert_called_once();self.pay.assert_not_called()

    def test_fallback_court_and_success_stops_all_candidates(self):
        j=self.job();self.fetch.return_value=self.availability(False,True);self.s.tick()
        self.assertEqual(self.book.call_args.args[0]['venue'],'court2');self.assertEqual(j['state'],'booked')
        self.now+=dt.timedelta(minutes=1);self.s.tick();self.book.assert_called_once()

    def test_waitlist_uses_fresh_queries_until_available(self):
        j=self.job();self.fetch.return_value=self.availability(False,False);self.s.tick()
        self.assertEqual(j['state'],'waiting');self.book.assert_not_called()
        self.s.tick();self.assertEqual(self.fetch.call_count,1)
        self.now+=dt.timedelta(seconds=30);self.fetch.return_value=self.availability();self.s.tick()
        self.assertEqual(self.fetch.call_count,2);self.book.assert_called_once()

    def test_unopened_empty_slots_continue_watch(self):
        j=self.job();self.fetch.return_value={'courts':[{'infoId':'court1','slots':[]}]};self.s.tick()
        self.assertEqual(j['state'],'waiting');self.book.assert_not_called()

    def test_single_scheduled_query_without_vacancy_ends(self):
        c=self.config();c.update(mode='scheduled',runAt=a.stamp());j=self.job(c)
        self.fetch.return_value=self.availability(False,False);self.s.tick()
        self.assertEqual(j['state'],'unavailable');self.book.assert_not_called()

    def test_cancel_during_query_prevents_post(self):
        j=self.job()
        def query(*args):self.s.cancel(j['id']);return self.availability()
        self.fetch.side_effect=query;self.s.tick()
        self.assertEqual(j['state'],'cancelled');self.book.assert_not_called()

    def test_deadline_during_query_prevents_post(self):
        j=self.job()
        def query(*args):self.now=dt.datetime(2026,9,19,9);return self.availability()
        self.fetch.side_effect=query;self.s.tick()
        self.assertEqual(j['state'],'expired');self.book.assert_not_called()

    def test_account_change_pauses(self):
        j=self.job();self.identity.return_value=('different','other');self.s.tick()
        self.assertEqual(j['state'],'needs_login');self.book.assert_not_called()

    def test_login_failure_never_submits(self):
        j=self.job();self.auth.side_effect=a.LoginRequired('学校认证失效');self.s.tick()
        self.assertEqual(j['state'],'needs_login');self.book.assert_not_called()

    def test_read_failures_backoff_and_pause_after_five(self):
        j=self.job();self.fetch.side_effect=TimeoutError()
        for _ in range(5):self.s.tick();self.now=a.local_time(j['nextCheckAt'])
        self.assertEqual(j['state'],'paused');self.book.assert_not_called()

    def test_overlap_blocked_even_different_candidates(self):
        self.job();c=self.config();c['candidates']=['court3'];j=self.s.save_draft(c)
        with self.assertRaisesRegex(ValueError,'重叠'):self.s.enable(j['id'],{})

    def test_rejection_is_not_retried_as_occupancy_by_guessing(self):
        j=self.job();self.book.return_value={'submission':{'outcome':'rejected','message':'次数限制'}};self.s.tick()
        self.assertEqual(j['state'],'attention');self.now+=dt.timedelta(minutes=1);self.s.tick();self.book.assert_called_once()

    def test_unknown_only_reconciles_read_operations(self):
        j=self.job();self.book.side_effect=TimeoutError();self.s.tick()
        self.assertEqual(j['state'],'unknown')
        client=Mock();client.query.return_value={'rows':[]}
        with patch.object(a,'ResourceAPI',return_value=client):
            for _ in range(3):self.now=a.local_time(j['nextCheckAt']);self.s.tick()
        self.assertEqual(j['state'],'attention');self.book.assert_called_once();self.pay.assert_not_called()

    def test_amount_cap_blocks_payment_after_success(self):
        c=self.config();c.update(pay=True,maxAmount='39');j=self.job(c);self.s.tick()
        self.assertEqual(j['state'],'booked');self.pay.assert_not_called();self.assertIn('上限',j['message'])

    def test_payment_uses_actual_amount_and_never_rebooks_after_failure(self):
        c=self.config();c.update(pay=True,maxAmount='50');j=self.job(c);self.s.tick()
        self.assertEqual(self.pay.call_args.args[1]['expectedAmount'],'40');self.assertEqual(j['state'],'booked')
        self.s.tick();self.book.assert_called_once();self.pay.assert_called_once()

    def test_cancel_while_booking_prevents_subsequent_payment(self):
        c=self.config();c.update(pay=True,maxAmount='50');j=self.job(c)
        def submit(*args,**kwargs):self.s.cancel(j['id']);return self.success()
        self.book.side_effect=submit;self.s.tick();self.assertEqual(j['state'],'booked');self.pay.assert_not_called()

    def test_accepted_payment_readback_required(self):
        c=self.config();c.update(pay=True,maxAmount='50');j=self.job(c);self.pay.return_value={'outcome':'accepted'};self.s.tick()
        self.assertEqual(j['state'],'payment_pending')
        client=Mock();client.query.return_value=dict(self.success()['order']['configuration'],feePayStatus='1',userName='account',feeOrderAmount='40',recordTimeStart='2026-09-19 10:00:00',recordTimeEnd='2026-09-19 12:00:00')
        with patch.object(a,'ResourceAPI',return_value=client):
            self.now=a.local_time(j['nextCheckAt']);self.s.tick()
        self.assertEqual(j['state'],'paid');self.pay.assert_called_once()

    def test_restart_mid_post_recovers_as_unknown_not_waiting(self):
        j=self.job();j.update(state='submitting',submittedAt=a.stamp(),selected='court1');self.s._save()
        other=a.Scheduler(threading.Lock(),self.path)
        self.assertEqual(other.jobs[j['id']]['state'],'unknown')
        self.assertNotIn('accountKey',other.snapshot()['jobs'][0]);self.book.assert_not_called()

    def test_failed_journal_write_prevents_post(self):
        self.job()
        with patch.object(a.os,'replace',side_effect=OSError('disk full')):
            with self.assertRaises(a.StateWriteError):self.s.tick()
        self.book.assert_not_called();self.assertIsNotNone(self.s.fatal)

    def test_maintenance_happens_before_scheduled_start(self):
        c=self.config();c['mode']='scheduled';j=self.job(c)
        self.auth.reset_mock();self.s.tick();self.auth.assert_called_once();self.book.assert_not_called()
        self.now+=dt.timedelta(minutes=5);self.s.tick();self.assertEqual(self.auth.call_count,2)
        self.assertEqual(j['state'],'waiting')

    def test_invalid_policy_rejected(self):
        for changes in ({'interval':1},{'until':'2026-09-19T11:00:00'},{'candidates':['court1','court1']},{'pay':True,'maxAmount':'NaN'}):
            c=self.config();c.update(changes)
            with self.assertRaises(ValueError):self.s.save_draft(c)

    def test_corrupt_storage_never_overwritten(self):
        self.path.write_text('not json');other=a.Scheduler(threading.Lock(),self.path)
        self.assertIsNotNone(other.fatal)
        with self.assertRaises(ValueError):other.save_draft(self.config())
        self.assertEqual(self.path.read_text(),'not json')

    def test_second_worker_cannot_execute_same_store(self):
        self.s.start()
        try:
            other=a.Scheduler(threading.Lock(),self.path);other.start()
            self.assertIsNotNone(other.fatal);self.assertIsNone(other.thread)
        finally:self.s.stop_event.set();self.s.thread.join(3)

    def test_near_expiry_refreshes_without_discarding_valid_session_on_failure(self):
        import base64
        expiry=(self.now+dt.timedelta(minutes=1)).replace(tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()
        token='header.'+base64.urlsafe_b64encode(json.dumps({'exp':expiry}).encode()).decode()+'.signature'
        credentials={'token':token,'ssoCookies':[{}]}
        self.auth.side_effect=[(credentials,{'renewed':False}),a.LoginRequired('不能续期')]
        self.assertEqual(self.s._credentials(),credentials)
        self.assertEqual(self.s.health['state'],'valid')
        self.assertIn('renewalWarning',self.s.health)
        self.assertEqual(self.auth.call_count,2)

    def test_job_journal_precedes_booking_and_payment(self):
        c=self.config();c.update(pay=True,maxAmount='50');j=self.job(c)
        def submit(*args,**kwargs):
            saved=json.loads(self.path.read_text())['jobs'][j['id']]
            self.assertEqual(saved['state'],'submitting');self.assertTrue(saved['submittedAt'])
            return self.success()
        def payment(*args,**kwargs):
            saved=json.loads(self.path.read_text())['jobs'][j['id']]
            self.assertEqual(saved['state'],'paying');self.assertEqual(saved['result']['order']['configuration']['feeOrderId'],'o1')
            return {'outcome':'insufficient_balance'}
        self.book.side_effect=submit;self.pay.side_effect=payment;self.s.tick()

    def test_mismatched_slot_does_not_change_requested_time(self):
        j=self.job();self.fetch.return_value={'courts':[{'infoId':'court1','slots':[{'start':'09:00','end':'11:00','available':True}]}]}
        self.s.tick();self.assertEqual(j['state'],'attention');self.book.assert_not_called()

    def test_foreground_queries_yield_to_initial_scheduled_deadline(self):
        c=self.config();c.update(mode='scheduled',runAt=a.stamp(self.now+dt.timedelta(seconds=40)));self.job(c)
        self.assertTrue(self.s.due_soon())

    def test_cancelled_query_exception_does_not_reactivate_job(self):
        j=self.job()
        def failed(*args):self.s.cancel(j['id']);raise TimeoutError()
        self.fetch.side_effect=failed;self.s.tick();self.assertEqual(j['state'],'cancelled');self.book.assert_not_called()


if __name__=='__main__':unittest.main()
