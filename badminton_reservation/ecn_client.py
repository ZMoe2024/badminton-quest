"""Authenticated read-only client with independent Python bootstrap/signing.

Usage: python ecn_client.py --credentials-file path/to/credentials.json
The file accepts {"cookie": "...", "token": "..."}; token may be omitted when
the Cookie header itself contains token=. No credentials are written by this client.
"""
from __future__ import annotations
import argparse
import base64
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

from .ecn_bootstrap import BootstrapError, context_from_bootstrap
from .ecn_parameter import ParameterGenerator
from .fetch_bootstrap import fetch_bootstrap
from .loader_cache import PUBLIC_LOADERS

ORIGIN = 'https://resm.lzjtu.edu.cn'


def normalize_credentials(credentials):
    credentials = dict(credentials)
    cookies = list(credentials.get('cookies', []))
    for part in credentials.get('cookie', '').strip().split(';'):
        if '=' in part:
            name, value = part.strip().split('=', 1)
            cookies.append({'name': name, 'value': value, 'domain': 'resm.lzjtu.edu.cn', 'path': '/'})
    credentials['cookies'] = cookies
    if not credentials.get('token'):
        credentials['token'] = next((unquote(c['value']) for c in cookies if c['name'] == 'token'), None)
    if not cookies:
        raise ValueError('缺少登录 Cookie')
    if not credentials.get('token'):
        raise ValueError('Cookie 中没有 token；还需提供 X-Access-Token（JSON 的 token 字段）')
    return credentials


def decode_response(response):
    value = response.json()
    if isinstance(value, str):
        encoded = ''.join(value[13:-6].split())
        value = json.loads(base64.b64decode(encoded, validate=True).decode('utf-8'))
    return value


class BootstrapClient:
    def __init__(self, credentials):
        self.credentials = normalize_credentials(credentials)
        self.session = requests.Session()
        self.generator = None
        self.parameter_name = None
        self.bootstrap_status = None
        self.loader_url = None

    def bootstrap(self):
        document = fetch_bootstrap(self.credentials, self.session)
        self.bootstrap_status = document['status']
        if not document.get('cd') or document.get('nsd') is None:
            raise BootstrapError('首页没有返回配置块；请检查 Cookie 是否有效')
        scripts = [url for url in document['scripts']
                   if urlsplit(url).scheme == 'https' and urlsplit(url).netloc == 'resm.lzjtu.edu.cn'
                   and urlsplit(url).path.endswith('.js')]
        if len(scripts) != 1:
            raise BootstrapError('无法唯一确定首页引用的防护脚本，需要核对页面结构')
        self.loader_url = scripts[0]
        literals, self.loader_validation = PUBLIC_LOADERS.load(self.session, self.loader_url)
        try:
            context = context_from_bootstrap(document['cd'], document['nsd'], literals=literals)
        except (ValueError, KeyError, IndexError, UnicodeError):
            # A site may replace code at the same URL before cache expiry.
            # Re-fetch code once, without replaying any business request.
            PUBLIC_LOADERS.invalidate(self.loader_url)
            if self.loader_validation['templatesSource'] == 'current-http-response':
                raise
            literals, self.loader_validation = PUBLIC_LOADERS.load(self.session, self.loader_url, force=True)
            context = context_from_bootstrap(document['cd'], document['nsd'], literals=literals)
        self.generator = ParameterGenerator(context)
        self.parameter_name = context['parameterName']
        return self

    def get(self, path='/hzsun-resm/msg/unReadCounts'):
        target = urlsplit(path)
        if target.scheme or target.netloc or not path.startswith('/') or path.startswith('//'):
            raise ValueError('只接受本站以 / 开始的接口路径')
        if self.generator is None:
            self.bootstrap()
        if self.parameter_name in [part.split('=', 1)[0] for part in target.query.split('&')]:
            raise ValueError('请传入不含旧 ecnMsZXb 的接口路径')
        parameter = self.generator.generate(path, flags=33555232)
        # The protection layer moves the original query into the signed envelope.
        # Keeping it on the wire duplicates it and the gateway rejects the request.
        response = self.session.get(ORIGIN + target.path, params={self.parameter_name: parameter},
                                    headers={'X-Access-Token': self.credentials['token'],
                                             'Referer': ORIGIN + '/', 'Accept': 'application/json, text/plain, */*'},
                                    timeout=25, allow_redirects=False)
        self.note_response(response)
        return response

    def note_response(self, response):
        if response.status_code in (400, 412):
            if self.loader_url:
                PUBLIC_LOADERS.invalidate(self.loader_url)
            self.generator = None

    def close(self):
        self.session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-file', type=Path, required=True, help='UTF-8 JSON，使用 - 从标准输入读取')
    args = parser.parse_args()
    credentials = json.load(sys.stdin) if str(args.credentials_file) == '-' else json.loads(args.credentials_file.read_text(encoding='utf-8-sig'))
    client = BootstrapClient(credentials)
    try:
        response = client.get()
        try:
            result = decode_response(response)
        except (ValueError, UnicodeError):
            result = None
        report = {'bootstrapStatus': client.bootstrap_status, 'httpStatus': response.status_code,
                  'businessCode': result.get('errCode') if isinstance(result, dict) else None,
                  'browserRequired': False, 'javascriptEngineRequired': False, 'bookingSubmitted': False}
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['businessCode'] == '0000' and response.status_code == 200 else 1
    finally:
        client.close()


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException) as exc:
        # requests exceptions can embed a URL containing a generated parameter.
        print(json.dumps({'errorType': type(exc).__name__,
                          'message': str(exc) if isinstance(exc, BootstrapError) else '运行失败；请检查凭据、网络和输入文件。'}, ensure_ascii=False))
        raise SystemExit(1)
