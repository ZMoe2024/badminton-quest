"""Offline contract checks: no browser, network, or real reservation."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation import badminton_booking as booking
from badminton_reservation import booking_submit_python as submit
from badminton_reservation import ecn_client
from badminton_reservation.badminton import CATALOG
from badminton_reservation.response import decode_result, unpack_body
from badminton_reservation.resm_api import encode_business
from badminton_reservation.ecn_bootstrap_loader import generate_bootstrap_source


def config():
    return {'venue': '主馆羽毛球场7', 'date': '2026-09-19', 'start': '12:00', 'end': '14:00'}


def blocks():
    row, _, _, _ = booking.resolve(config())
    return [{'infoId': row['infoId'], 'minBlockNum': 1, 'maxBlockNum': 1,
             'resUseTimeBlockInfoList': [{'blockStartTime': a, 'blockEndTime': z}
                 for a, z in [('12:00', '14:00'), ('16:00', '17:00'), ('17:00', '18:00')]]}]


class ModuleTests(unittest.TestCase):
    def test_bundled_loader_asset(self):
        # Lengths verified against the original downloaded loader before packaging.
        self.assertEqual(len(generate_bootstrap_source(1)), 189168)
        self.assertEqual(len(generate_bootstrap_source(1234)), 189178)

    def test_catalog_ids_unique(self):
        rows = json.loads(CATALOG.read_text(encoding='utf-8'))['courts']
        self.assertEqual(len(rows), len({r['infoId'] for r in rows}))
        self.assertTrue(all('羽毛球' in r['name'] for r in rows))

    def test_exact_and_invalid_slots(self):
        row, _, start, end = booking.resolve(config())
        booking.validate_slot(blocks(), row['infoId'], start, end)
        for a, z in [('12:30', '14:00'), ('16:00', '18:00')]:
            with self.assertRaises(ValueError):
                booking.validate_slot(blocks(), row['infoId'], a, z)

    def test_invalid_selection(self):
        for update in [{'venue': '不存在的场地'}, {'date': '2026-02-30'}, {'end': '10:00'}]:
            with self.assertRaises(ValueError):
                booking.resolve(config() | update)

    def test_business_encoding(self):
        self.assertEqual(encode_business(''), '')
        data = {'location': '羽毛球', 'checked': False}
        self.assertEqual(unpack_body(encode_business(data)), data)
        self.assertEqual(decode_result(json.dumps(encode_business({'errCode': '0000'}))), {'errCode': '0000'})
        self.assertIsNone(decode_result('<html>invalid response</html>'))

    def test_get_consumes_original_query(self):
        client = ecn_client.BootstrapClient({'cookie': 'token=test'})
        client.generator = Mock()
        client.generator.generate.return_value = 'generated'
        client.parameter_name = 'ecnMsZXb'
        client.session = Mock()
        path = '/hzsun-resm/example?id=encoded&t=encoded'
        client.get(path)
        client.generator.generate.assert_called_once_with(path, flags=33555232)
        args, kwargs = client.session.get.call_args
        self.assertEqual(args[0], ecn_client.ORIGIN + '/hzsun-resm/example')
        self.assertEqual(kwargs['params'], {'ecnMsZXb': 'generated'})

    @patch.object(booking, 'run')
    @patch.object(booking, 'ResourceAPI')
    def test_check_never_submits_and_form_mapping(self, api, runner):
        row, _, _, _ = booking.resolve(config())
        api.return_value.query.side_effect = [
            {'infoId': row['infoId'], 'infoStatus': '1'}, blocks(),
            {'managePropertyConifgVos': [{'propertyColumnCode': 'LXDH', 'propertyId': 'fresh-property'}]}]
        report = booking.execute({}, config(), submit=False)
        self.assertEqual(report['submission']['outcome'], 'not_submitted')
        runner.assert_not_called()
        api.return_value.close.assert_called_once()

    @patch.object(booking, 'run')
    @patch.object(booking, 'ResourceAPI')
    def test_submit_maps_selected_resource(self, api, runner):
        row, _, _, _ = booking.resolve(config())
        api.return_value.query.side_effect = [
            {'infoId': row['infoId'], 'infoStatus': '1'}, blocks(),
            {'managePropertyConifgVos': [{'propertyColumnCode': 'LXDH', 'propertyId': 'fresh-property'}]}]
        runner.return_value = {'outcome': 'rejected'}
        booking.execute({}, config(), submit=True)
        runner.assert_called_once()
        payload = runner.call_args.kwargs['booking_data']
        self.assertEqual(payload['infoId'], row['infoId'])
        self.assertEqual(payload['occupyTimeStart'], '2026-09-19 12:00:00')
        self.assertEqual(payload['formManagePropertyValueList'][0]['propertyId'], 'fresh-property')

    @patch.object(booking, 'run')
    @patch.object(booking, 'ResourceAPI')
    def test_failed_validation_never_submits(self, api, runner):
        api.return_value.query.return_value = {'infoId': 'wrong', 'infoStatus': '1'}
        with self.assertRaises(ValueError):
            booking.execute({}, config(), submit=True)
        runner.assert_not_called()
        api.return_value.close.assert_called_once()

    def test_raw_post_unknown_result_blocks_repeat(self):
        claims = base64.urlsafe_b64encode(json.dumps({'username': 'test-user', 'exp': 9999999999}).encode()).decode().rstrip('=')
        token = 'header.' + claims + '.signature'
        inputs = {'currentUser': base64.b64encode(json.dumps({'username': 'test-user', 'userId': 'test-id'}).encode()).decode()}
        payload = {'infoId': 'court-test', 'location': '测试羽毛球', 'occupyTimeStart': '2026-09-19 12:00:00',
                   'occupyTimeEnd': '2026-09-19 14:00:00'}
        client = Mock()
        client.credentials = {'token': token}
        client.generator.generate.return_value = 'independent-url-parameter'
        client.parameter_name = 'ecnMsZXb'
        client.session.post.side_effect = TimeoutError()
        with tempfile.TemporaryDirectory() as folder, patch.object(submit, '__file__', str(Path(folder) / 'submit.py')), patch.object(submit, 'BootstrapClient', return_value=client):
            report = submit.run(inputs, submit=True, booking_data=payload)
            self.assertEqual(report['outcome'], 'unknown')
            sent = client.session.post.call_args.kwargs
            self.assertEqual(sent['params'], {'ecnMsZXb': 'independent-url-parameter'})
            self.assertFalse(sent['data'].startswith(b'"'))
            self.assertEqual(unpack_body(sent['data'].decode())['jobNum'], 'test-user')
            with self.assertRaises(ValueError):
                submit.run(inputs, submit=True, booking_data=payload)
            self.assertEqual(client.session.post.call_count, 1)
            record_text = next((Path(folder) / 'state/attempts').glob('*.json')).read_text(encoding='utf-8')
            self.assertNotIn(token, record_text)


if __name__ == '__main__':
    unittest.main()
