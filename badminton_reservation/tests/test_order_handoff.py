import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from badminton_reservation import payment, workflow, cli

CONFIG = {'venue': '主馆羽毛球场7', 'date': '2026-09-19', 'start': '12:00', 'end': '14:00'}


def submission():
    return {'outcome': 'success', 'bookingCreated': True,
            'reservation': {'code': 2, 'occupyId': 'reservation', 'infoId': 'court', 'userId': 'user'},
            'requestedResource': {'infoId': 'court', 'userId': 'user'},
            'preview': {'start': '2026-09-19 12:00:00', 'end': '2026-09-19 14:00:00'}}


class HandoffTests(unittest.TestCase):
    def test_exact_reservation_query_and_persisted_order(self):
        client = Mock()
        client.query.return_value = {'feeOrderId': 'order', 'userName': 'account', 'feeOrderAmount': 40,
            'recordTimeStart': submission()['preview']['start'], 'recordTimeEnd': submission()['preview']['end'],
            'feeOrderStatus': '0', 'feePayStatus': '0'}
        with tempfile.TemporaryDirectory() as folder, patch.object(payment, 'ResourceAPI', return_value=client), \
             patch.object(payment, 'expected_identity', return_value=('account', 'user')):
            report = payment.resolve_order({}, submission(), state_dir=folder)
            client.query.assert_called_once_with(payment.DETAIL_PATH,
                {'infoId': 'court', 'occupyId': 'reservation', 'userId': 'user'})
            self.assertEqual(json.loads(Path(report['orderConfigFile']).read_text(encoding='utf-8')),
                             report['configuration'])
            self.assertEqual(report['configuration']['feeOrderId'], 'order')
            client.session.post.assert_not_called()

    def test_missing_id_or_mismatched_identity_never_looks_up_order(self):
        for changes in ({'occupyId': ''}, {'userId': 'other'}, {'infoId': 'other'}, {'code': 3}):
            record = submission(); record['reservation'].update(changes)
            with patch.object(payment, 'ResourceAPI') as api, \
                 patch.object(payment, 'expected_identity', return_value=('account', 'user')):
                with self.assertRaises(ValueError): payment.resolve_order({}, record)
                api.assert_not_called()

    def test_failed_or_unknown_booking_never_pays(self):
        for outcome in ('rejected', 'unknown'):
            with patch.object(workflow, 'authenticate', return_value=({}, {})), \
                 patch.object(workflow, 'execute', return_value={'submission': {'outcome': outcome}}) as execute, \
                 patch.object(workflow, 'resolve_order') as resolve, patch.object(workflow, 'pay') as pay:
                workflow.book(CONFIG, submit=True, pay_after=True, expected_amount=40)
                execute.assert_called_once(); resolve.assert_not_called(); pay.assert_not_called()

    def test_success_handoff_only_pays_when_opted_in_and_preserves_expected_amount(self):
        for enabled in (False, True):
            with patch.object(workflow, 'authenticate', return_value=({}, {})), \
                 patch.object(workflow, 'execute', return_value={'submission': submission()}), \
                 patch.object(workflow, 'resolve_order', return_value={'configuration': {'feeOrderId': 'new-order', 'expectedAmount': '99'}}), \
                 patch.object(workflow, 'pay', return_value={'outcome': 'insufficient_balance'}) as pay:
                result = workflow.book(CONFIG, submit=True, pay_after=enabled, expected_amount=40)
                if enabled:
                    pay.assert_called_once_with({}, {'feeOrderId': 'new-order', 'expectedAmount': '40'}, submit=True)
                    self.assertEqual(result['payment']['outcome'], 'insufficient_balance')
                else: pay.assert_not_called()

    def test_lookup_failure_preserves_created_reservation_no_retry(self):
        with patch.object(workflow, 'authenticate', return_value=({}, {})), \
             patch.object(workflow, 'execute', return_value={'submission': submission()}) as execute, \
             patch.object(workflow, 'resolve_order', side_effect=TimeoutError('secret-url')), \
             patch.object(workflow, 'pay') as pay:
            result = workflow.book(CONFIG, submit=True, pay_after=True, expected_amount=40)
            self.assertTrue(result['submission']['bookingCreated'])
            self.assertEqual(result['submission']['reservation']['occupyId'], 'reservation')
            self.assertNotIn('secret-url', json.dumps(result))
            execute.assert_called_once(); pay.assert_not_called()

    def test_invalid_amount_rejected_before_booking(self):
        for amount in (0, -1, 'NaN', 'Infinity', 'bad'):
            with patch.object(workflow, 'authenticate') as auth:
                with self.assertRaises(ValueError):
                    workflow.book(CONFIG, submit=True, pay_after=True, expected_amount=amount)
                auth.assert_not_called()

    def test_dynamic_amount_uses_new_order_quote(self):
        for quote in ('20', '40', '60'):
            with patch.object(workflow, 'authenticate', return_value=({}, {})), \
                 patch.object(workflow, 'execute', return_value={'submission': submission()}), \
                 patch.object(workflow, 'resolve_order', return_value={'configuration': {'feeOrderId': 'new-order', 'expectedAmount': quote}}), \
                 patch.object(workflow, 'pay', return_value={'outcome': 'insufficient_balance'}) as pay:
                workflow.book(CONFIG, submit=True, pay_after=True)
                pay.assert_called_once_with({}, {'feeOrderId': 'new-order', 'expectedAmount': quote}, submit=True)

    def test_cli_payment_flags_reach_workflow(self):
        with patch.object(cli, 'book', return_value={}) as book:
            self.assertEqual(cli.main(['submit', '--pay', '--expected-amount', '40']), 0)
            self.assertTrue(book.call_args.kwargs['pay_after'])
            self.assertEqual(book.call_args.kwargs['expected_amount'], '40')

    def test_public_python_api_passes_payment_options(self):
        from badminton_reservation import book
        with patch.object(workflow, 'book', return_value={'payment': {'outcome': 'insufficient_balance'}}) as run:
            result = book(CONFIG, submit=True, pay_after=True)
            self.assertTrue(run.call_args.kwargs['pay_after'])
            self.assertIsNone(run.call_args.kwargs['expected_amount'])
            self.assertEqual(result['payment']['outcome'], 'insufficient_balance')


if __name__ == '__main__': unittest.main()
