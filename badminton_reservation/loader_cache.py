"""Bounded process-local cache of public protection code, never session context."""
from collections import OrderedDict
import copy
import hashlib
import threading
import time

from .ecn_bootstrap import BootstrapError
from .loader_templates import extract_templates


class LoaderCache:
    def __init__(self, *, capacity=8, max_age=3600, clock=time.monotonic):
        self.capacity, self.max_age, self.clock = capacity, max_age, clock
        self.entries = OrderedDict()
        self.templates = OrderedDict()
        self.lock = threading.RLock()

    def invalidate(self, url):
        with self.lock:
            self.entries.pop(url, None)

    def _remember(self, cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > self.capacity:
            cache.popitem(last=False)

    def _policy(self, headers):
        directives = {}
        for part in headers.get('cache-control', '').lower().split(','):
            key, _, value = part.strip().partition('=')
            directives[key] = value.strip('"')
        # Only explicitly public code may cross client boundaries. Responses
        # carrying cookies or varying on identity are always fetched afresh.
        varies = {v.strip().lower() for v in headers.get('vary', '').split(',') if v.strip()}
        allowed = ('public' in directives and not {'private', 'no-store'} & directives.keys()
                   and 'set-cookie' not in headers and varies <= {'accept-encoding'})
        try:
            ttl = max(0, min(self.max_age, int(directives.get('max-age', '0')))
                      - max(0, int(headers.get('age', '0'))))
        except ValueError:
            ttl = 0
        if 'no-cache' in directives:
            ttl = 0
        return allowed, ttl

    def load(self, session, url, *, force=False):
        # Single flight: concurrent lanes download/parse the same code once.
        # This lock never covers business calls or account-specific decoding.
        with self.lock:
            entry = self.entries.get(url)
            if not force and entry and self.clock() < entry['expires']:
                self.entries.move_to_end(url)
                return self._result(entry, 'memory-cache')
            headers = {}
            if entry and not force and entry['headers'].get('etag'):
                headers['If-None-Match'] = entry['headers']['etag']
            response = session.get(url, headers=headers, timeout=25, allow_redirects=False)
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            try:
                if response.status_code == 304 and entry and headers:
                    merged = dict(entry['headers'], **response_headers)
                    allowed, ttl = self._policy(merged)
                    entry = dict(entry, headers=merged, expires=self.clock() + ttl)
                    if allowed:
                        self._remember(self.entries, url, entry)
                    else:
                        self.entries.pop(url, None)
                    return self._result(entry, 'http-revalidated')
                if response.status_code != 200:
                    self.entries.pop(url, None)
                    raise BootstrapError('防护脚本读取失败，HTTP ' + str(response.status_code))
                content = response.content
                digest = hashlib.sha256(content).hexdigest()
                allowed, ttl = self._policy(response_headers)
                parsed = self.templates.get(digest) if allowed else None
                if parsed is None:
                    parsed = extract_templates(content)
                    if allowed:
                        self._remember(self.templates, digest, parsed)
                else:
                    self.templates.move_to_end(digest)
                entry = {'headers': response_headers, 'expires': self.clock() + ttl,
                         'literals': parsed[0], 'validation': {
                             'status': 200, 'bytes': len(content), 'sha256': digest,
                             'lfSha256': hashlib.sha256(content.replace(b'\r\n', b'\n')).hexdigest(),
                             'sourceSha256': parsed[1],
                             'contentType': response_headers.get('content-type')}}
                if allowed:
                    self._remember(self.entries, url, entry)
                else:
                    self.entries.pop(url, None)
                return self._result(entry, 'current-http-response')
            except Exception:
                self.entries.pop(url, None)
                raise
            finally:
                response.close()

    @staticmethod
    def _result(entry, source):
        return copy.deepcopy(entry['literals']), dict(entry['validation'], templatesSource=source)


PUBLIC_LOADERS = LoaderCache()
