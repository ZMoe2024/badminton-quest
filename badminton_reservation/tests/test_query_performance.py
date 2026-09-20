"""Cache freshness, account isolation and read-operation reuse; no live bookings."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from badminton_reservation import availability, badminton, ecn_client, session
from badminton_reservation.ecn_bootstrap import BootstrapError
from badminton_reservation.loader_cache import LoaderCache
from badminton_reservation.query_scope import borrow_client, read_scope
from badminton_reservation.resm_api import ResourceAPI


def response(status=200, body=b'code', headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result._content_consumed = True
    result.headers.update(headers or {})
    return result


PUBLIC = {'Cache-Control': 'public, max-age=60', 'ETag': '"one"'}
URL = 'https://resm.lzjtu.edu.cn/current.js'


class LoaderCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.cache = LoaderCache(capacity=2, clock=lambda: self.now)
        self.parse = patch('badminton_reservation.loader_cache.extract_templates',
                           side_effect=lambda data: ([{'value': data.decode()}], data.hex()))
        self.parser = self.parse.start()
        self.addCleanup(self.parse.stop)
        self.http = Mock()
        self.http.get.return_value = response(headers=PUBLIC)

    def test_public_cache_and_template_copy_do_not_retain_session(self):
        first, _ = self.cache.load(self.http, URL)
        first[0]['value'] = 'caller mutation'
        second_http = Mock()
        second, info = self.cache.load(second_http, URL)
        self.assertEqual(second[0]['value'], 'code')
        self.assertEqual(info['templatesSource'], 'memory-cache')
        second_http.get.assert_not_called()
        self.http.get.assert_called_once()
        self.parser.assert_called_once()

    def test_expiry_revalidates_etag_and_changed_body_reparses(self):
        self.cache.load(self.http, URL)
        self.now = 61
        self.http.get.return_value = response(304)
        _, info = self.cache.load(self.http, URL)
        self.assertEqual(info['templatesSource'], 'http-revalidated')
        self.assertEqual(self.http.get.call_args.kwargs['headers'], {'If-None-Match': '"one"'})
        self.now = 122
        self.http.get.return_value = response(body=b'new-code', headers=dict(PUBLIC, ETag='"two"'))
        literals, _ = self.cache.load(self.http, URL)
        self.assertEqual(literals[0]['value'], 'new-code')
        self.assertEqual(self.parser.call_count, 2)

    def test_non_public_and_identity_dependent_responses_are_not_cached(self):
        for extra in [{'Cache-Control': 'private, max-age=60'}, {'Cache-Control': 'no-store, public'},
                      {'Set-Cookie': 'session=synthetic'}, {'Vary': 'Cookie'},
                      {'Vary': '*'}, {'Vary': 'Authorization'}, {'Vary': 'User-Agent'},
                      {'Cache-Control': ''}]:
            with self.subTest(headers=extra):
                cache = LoaderCache()
                http = Mock()
                http.get.return_value = response(headers=dict(PUBLIC, **extra))
                cache.load(http, URL)
                cache.load(http, URL)
                self.assertEqual(http.get.call_count, 2)
                self.assertFalse(cache.entries)
                self.assertFalse(cache.templates)

    def test_no_cache_and_age_require_revalidation(self):
        for extra in [{'Cache-Control': 'public, no-cache, max-age=60'}, {'Age': '60'}]:
            cache, http = LoaderCache(), Mock()
            http.get.return_value = response(headers=dict(PUBLIC, **extra))
            cache.load(http, URL)
            cache.load(http, URL)
            self.assertEqual(http.get.call_count, 2)

    def test_failure_does_not_serve_stale_or_poison_cache(self):
        self.cache.load(self.http, URL)
        self.now = 61
        self.http.get.return_value = response(500)
        with self.assertRaises(BootstrapError): self.cache.load(self.http, URL)
        self.assertNotIn(URL, self.cache.entries)
        self.http.get.return_value = response(body=b'broken', headers=PUBLIC)
        self.parser.side_effect = BootstrapError('invalid code')
        with self.assertRaises(BootstrapError): self.cache.load(self.http, URL)
        self.assertNotIn(URL, self.cache.entries)

    def test_new_url_downloads_but_same_content_reuses_parse_and_bounds_memory(self):
        for number in range(3): self.cache.load(self.http, URL + '?' + str(number))
        self.assertEqual(self.http.get.call_count, 3)
        self.parser.assert_called_once()
        self.assertEqual(len(self.cache.entries), 2)

    def test_concurrent_lanes_fetch_public_code_once(self):
        gate = threading.Barrier(3)
        def load(_):
            gate.wait(timeout=3)
            return self.cache.load(self.http, URL)
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(len(list(pool.map(load, range(3)))), 3)
        self.http.get.assert_called_once()
        self.parser.assert_called_once()

    def test_invalidate_bypasses_old_etag(self):
        self.cache.load(self.http, URL)
        self.cache.invalidate(URL)
        self.cache.load(self.http, URL)
        self.assertEqual(self.http.get.call_count, 2)
        self.assertEqual(self.http.get.call_args.kwargs['headers'], {})


def credentials(name='one'):
    return {'token': name, 'currentUser': name, 'cookies': [
        {'name': 'token', 'value': name, 'domain': 'resm.lzjtu.edu.cn', 'path': '/'}]}


class ReadScopeTests(unittest.TestCase):
    def setUp(self):
        self.clients = []
        def create(data):
            client = Mock()
            client.credentials = copy.deepcopy(data)
            client.session.cookies = requests.cookies.RequestsCookieJar()
            for c in data['cookies']:
                client.session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'])
            self.clients.append(client)
            return client
        self.factory = Mock(side_effect=create)

    def test_probe_updated_cookie_handoff_reuses_and_closes_once(self):
        data = credentials()
        with read_scope():
            with borrow_client(data, self.factory) as first:
                first.session.cookies.set('protection', 'new', domain='resm.lzjtu.edu.cn', path='/')
                updated = dict(data, cookies=session.cookie_rows(first.session.cookies))
            with borrow_client(updated, self.factory) as second: self.assertIs(first, second)
            first.close.assert_not_called()
        self.factory.assert_called_once()
        first.close.assert_called_once()

    def test_accounts_tokens_cookie_changes_and_actions_are_isolated(self):
        with read_scope():
            for data in [credentials(), credentials('two'), dict(credentials(), token='renewed'),
                         dict(credentials(), currentUser='different-profile'),
                         dict(credentials(), cookies=credentials('changed-cookie')['cookies'])]:
                with borrow_client(data, self.factory): pass
        with read_scope():
            with borrow_client(credentials(), self.factory): pass
        self.assertEqual(self.factory.call_count, 6)
        for c in self.clients: c.close.assert_called_once()

    def test_scope_failure_closes_and_drops_client(self):
        with read_scope():
            with self.assertRaises(ValueError):
                with borrow_client(credentials(), self.factory): raise ValueError('failed query')
            with borrow_client(credentials(), self.factory): pass
        self.assertEqual(self.factory.call_count, 2)
        for c in self.clients: c.close.assert_called_once()

    def test_nested_and_concurrent_actions_cannot_share_clients(self):
        with read_scope():
            with borrow_client(credentials(), self.factory) as parent: pass
            with read_scope():
                with borrow_client(credentials(), self.factory) as nested: self.assertIsNot(parent, nested)
            with ThreadPoolExecutor(max_workers=1) as pool:
                def action():
                    with read_scope():
                        with borrow_client(credentials(), self.factory) as child: return child
                self.assertIsNot(parent, pool.submit(action).result(timeout=3))
            with borrow_client(credentials(), self.factory) as again: self.assertIs(parent, again)
        self.assertEqual(self.factory.call_count, 3)

    def test_no_scope_retains_original_close_behavior(self):
        for _ in range(2):
            with borrow_client(credentials(), self.factory): pass
        self.assertEqual(self.factory.call_count, 2)
        for c in self.clients: c.close.assert_called_once()

    def test_real_probe_catalog_availability_use_one_client_and_refresh_data(self):
        data = credentials()
        client = self.factory(data)
        client.get.return_value = response(body=b'{"errCode":"0000"}')
        client.query.return_value = []
        client.post_query.return_value = {'resourceTreeVos': []}
        factory = Mock(return_value=client)
        with patch.object(session, 'ResourceAPI', factory), patch.object(badminton, 'ResourceAPI', factory), \
             patch.object(availability, 'ResourceAPI', factory), patch.object(badminton, 'write_badminton'), \
             patch.object(availability, 'fetch_court', return_value={'slots': []}) as fetch:
            with read_scope():
                updated, valid = session.probe(data)
                self.assertTrue(valid)
                badminton.refresh(updated)
                availability.fetch_availability(updated, [{'infoId': 'a', 'name': 'A'}], '2026-09-21')
                availability.fetch_availability(updated, [{'infoId': 'a', 'name': 'A'}], '2026-09-22')
            factory.assert_called_once()
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(client.query.call_count, 2)
            client.close.assert_called_once()


class BootstrapRecoveryTests(unittest.TestCase):
    def test_cached_code_mismatch_refreshes_once_before_business_request(self):
        client = ecn_client.BootstrapClient(credentials())
        self.addCleanup(client.close)
        document = dict(status=412, cd='configuration', nsd=1, scripts=[URL])
        with patch.object(ecn_client, 'fetch_bootstrap', return_value=document), \
             patch.object(ecn_client, 'PUBLIC_LOADERS') as cache, \
             patch.object(ecn_client, 'context_from_bootstrap', side_effect=[
                 BootstrapError('changed code'), {'parameterName': 'ecnMsZXb'}]), \
             patch.object(ecn_client, 'ParameterGenerator'):
            cache.load.side_effect = [([], {'templatesSource': 'memory-cache'}),
                                      ([], {'templatesSource': 'current-http-response'})]
            client.bootstrap()
            self.assertEqual(cache.load.call_count, 2)
            self.assertTrue(cache.load.call_args.kwargs['force'])
            cache.invalidate.assert_called_once_with(URL)

    def test_rejection_invalidates_without_replaying_request(self):
        client = ResourceAPI(credentials())
        self.addCleanup(client.close)
        client.loader_url, client.parameter_name = URL, 'ecnMsZXb'
        client.generator = Mock()
        with patch.object(client.session, 'post', return_value=response(412, b'rejected')) as post, \
             patch.object(ecn_client, 'PUBLIC_LOADERS') as cache:
            with self.assertRaises(ValueError):
                client.post_query('/hzsun-resm/sub/occupy/queryTimetableEmploy', {})
            post.assert_called_once()
            cache.invalidate.assert_called_once_with(URL)
            self.assertIsNone(client.generator)


if __name__ == '__main__': unittest.main()
