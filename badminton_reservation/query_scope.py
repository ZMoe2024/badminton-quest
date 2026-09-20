"""Reuse a verified client only inside one read operation and one credential set."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json

from .ecn_client import normalize_credentials

_scope = ContextVar('school_read_scope', default=None)


def _key(credentials):
    normalized = normalize_credentials(credentials)
    cookies = {(c['domain'], c.get('path', '/'), c['name']): c['value']
               for c in normalized['cookies']}
    value = [normalized['token'], normalized.get('currentUser'),
             normalized.get('userAgent', 'Mozilla/5.0'), sorted(cookies.items())]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).digest()


@contextmanager
def read_scope():
    """A fresh boundary per action, including nested actions; never a global pool."""
    clients = {}
    token = _scope.set(clients)
    try:
        yield
    finally:
        _scope.reset(token)
        for client in {id(c): c for c in clients.values()}.values():
            client.close()


@contextmanager
def borrow_client(credentials, factory):
    clients = _scope.get()
    if clients is None:
        client = factory(credentials)
        try:
            yield client
        finally:
            client.close()
        return
    key = _key(credentials)
    client = clients.get(key)
    if client is None:
        client = factory(credentials)
        clients[key] = client
    try:
        yield client
    except BaseException:
        for alias in [k for k, c in clients.items() if c is client]:
            del clients[alias]
        client.close()
        raise
    else:
        # probe() returns updated cookies. Register precisely that snapshot so
        # its subsequent directory and availability calls reuse this client.
        updated = dict(credentials, token=client.credentials['token'], cookies=[
            {'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path}
            for c in client.session.cookies])
        updated.pop('cookie', None)
        clients[_key(updated)] = client
