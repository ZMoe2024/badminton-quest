import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation import payment
from badminton_reservation.response import unpack_body

CONFIG = {'infoId': 'court', 'occupyId': 'reservation', 'feeOrderId': 'order', 'expectedAmount': 40,
          'start': '2026-09-19 12:00:00', 'end': '2026-09-19 14:00:00'}


class PaymentTests(unittest.TestCase):
    def client(self, result=None):
        client = Mock()
        client.credentials = {'token': 'secret-token'}
        client.parameter_name = 'ecnMsZXb'
        client.generator.generate.return_value = 'fresh-parameter'
        client.query.return_value = {'feeOrderId': 'order', 'userName': 'test-user', 'feeOrderAmount': 40,
            'recordTimeStart': CONFIG['start'], 'recordTimeEnd': CONFIG['end'], 'feePayStatus': '0',
            'feeOrderStatus': '0', 'chargeMode': '7', 'infoName': 'court-name', 'typeName': 'badminton'}
        client.session.post.return_value = Mock(status_code=200, text=json.dumps(result or {
            'errCode': '0001', 'customMess': '易通支付失败：钱包余额不足'}))
        return client

    def test_preview_never_pays(self):
        client = self.client()
        with patch.object(payment, 'ResourceAPI', return_value=client), patch.object(payment, 'expected_identity', return_value=('test-user', 'test-id')):
            result = payment.pay({}, CONFIG)
        client.session.post.assert_not_called()
        self.assertEqual(result['outcome'], 'not_submitted')

    def test_order_identity_amount_and_time_changes_stop_payment(self):
        for changes in [{'feeOrderId': 'other'}, {'userName': 'other'}, {'feeOrderAmount': 41},
                        {'recordTimeStart': 'other'}, {'feePayStatus': '1'}, {'chargeMode': '8'}, {'feeOrderStatus': '3'}]:
            client = self.client(); client.query.return_value.update(changes)
            with patch.object(payment, 'ResourceAPI', return_value=client), patch.object(payment, 'expected_identity', return_value=('test-user', 'test-id')):
                with self.assertRaises(ValueError): payment.pay({}, CONFIG, submit=True)
            client.session.post.assert_not_called()

    def test_real_request_shape_and_insufficient_balance(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as folder, patch.object(payment, 'ResourceAPI', return_value=client), patch.object(payment, 'expected_identity', return_value=('test-user', 'test-id')):
            result = payment.pay({}, CONFIG, submit=True, state_dir=folder)
            self.assertEqual(result['outcome'], 'insufficient_balance')
            self.assertFalse(result['paymentCompleted'])
            self.assertEqual(result['paymentAttempts'], 1)
            sent = client.session.post.call_args.kwargs
            body = unpack_body(sent['data'].decode())
            self.assertEqual(body, {'feeOrderId': 'order', 'payMode': '7', 'productName': 'court-name',
                'tranType': 'badminton', 'userNo': 'test-user', 'equipmentType': 'pc', 'infoId': 'court', 'userId': 'test-id'})
            self.assertFalse(sent['data'].startswith(b'"'))
            self.assertFalse(sent['allow_redirects'])
            self.assertEqual(sent['params'], {'ecnMsZXb': 'fresh-parameter'})
            text = next(Path(folder).glob('*.json')).read_text(encoding='utf-8')
            self.assertNotIn('secret-token', text)
            self.assertFalse(list(Path(folder).glob('*.lock')))

    def test_timeout_and_accepted_response_block_duplicate(self):
        for timeout in (True, False):
            client = self.client({'errCode': '0000', 'responseResult': {'return_url': 'https://example.invalid'}})
            if timeout: client.session.post.side_effect = TimeoutError()
            with tempfile.TemporaryDirectory() as folder, patch.object(payment, 'ResourceAPI', return_value=client), patch.object(payment, 'expected_identity', return_value=('test-user', 'test-id')):
                result = payment.pay({}, CONFIG, submit=True, state_dir=folder)
                self.assertEqual(result['outcome'], 'unknown' if timeout else 'accepted')
                self.assertIsNone(result['paymentCompleted'])
                with self.assertRaises(ValueError): payment.pay({}, CONFIG, submit=True, state_dir=folder)
                client.session.post.assert_called_once()


if __name__ == '__main__': unittest.main()
