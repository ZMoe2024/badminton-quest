"""Read the server bootstrap. Inputs and raw material stay on the stdin/stdout pipe."""
import json
import re
import sys
from urllib.parse import urljoin

import requests


def fetch_bootstrap(inputs, session=None):
    session = session or requests.Session()
    session.headers['User-Agent'] = inputs.get('userAgent', 'Mozilla/5.0')
    for cookie in inputs.get('cookies', []):
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'],
                            secure=cookie.get('secure', False),
                            expires=cookie['expires'] if (cookie.get('expires') or 0) > 0 else None)
    response = session.get('https://resm.lzjtu.edu.cn/', timeout=25)
    html = response.content.decode('utf-8', errors='replace')
    cd = re.search(r'\$_ts\.cd\s*=\s*([\'"])(.*?)\1', html, re.S)
    nsd = re.search(r'\$_ts\.nsd\s*=\s*(\d+)', html)
    scripts = re.findall(r'<script\b[^>]*?src\s*=\s*[\'"]([^\'"]+)', html, re.I)
    return {'status': response.status_code, 'html': html, 'cd': cd.group(2) if cd else None,
            'nsd': int(nsd.group(1)) if nsd else None, 'scripts': [urljoin(response.url, s) for s in scripts]}


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(fetch_bootstrap(json.load(sys.stdin)), ensure_ascii=False))
