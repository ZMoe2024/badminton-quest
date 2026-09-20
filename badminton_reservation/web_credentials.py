"""Validate manually supplied school credentials without accepting arbitrary targets."""
import base64
import json
import re
import time
from urllib.parse import unquote
from .ecn_client import normalize_credentials


def prepare_credentials(value):
    if not isinstance(value, dict):
        raise ValueError('请填写 Cookie 和 Token，或导入凭据 JSON')
    result = {}
    for key, limit in [('cookie', 30000), ('token', 12000), ('userAgent', 1000)]:
        text = value.get(key, '')
        if not isinstance(text, str) or len(text) > limit or '\r' in text or '\n' in text:
            raise ValueError('Cookie、Token 或 User-Agent 格式不正确，请复制值本身')
        result[key] = text.strip()
    if result['cookie'].lower().startswith('cookie:'):
        result['cookie'] = result['cookie'][7:].strip()
    if result['token'].lower().startswith('x-access-token:'):
        result['token'] = result['token'][15:].strip()
    for key, allowed in [('cookies', {'resm.lzjtu.edu.cn', 'lzjtu.edu.cn'}),
                         ('ssoCookies', {'authserver.lzjtu.edu.cn', 'lzjtu.edu.cn'})]:
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Cookie 列表格式不正确')
        result[key] = []
        for row in rows:
            if not isinstance(row, dict): raise ValueError('Cookie 列表格式不正确')
            domain = row.get('domain', '')
            name, content, path = row.get('name'), row.get('value'), row.get('path', '/')
            if (not isinstance(domain, str) or domain.lstrip('.') not in allowed or
                not isinstance(name, str) or not re.fullmatch(r'[\w.-]{1,200}', name) or
                not isinstance(content, str) or len(content) > 30000 or
                any(c in content for c in '\r\n') or not isinstance(path, str) or
                not path.startswith('/') or any(c in path for c in '\r\n')):
                raise ValueError('仅接受本校预约网站或统一认证的 Cookie')
            expiry = row.get('expires')
            if expiry is not None and (not isinstance(expiry, (int, float)) or not -1 <= expiry <= 253402300799):
                raise ValueError('Cookie 有效期格式不正确')
            result[key].append(dict(name=name, value=content, domain=domain, path=path,
                                    secure=bool(row.get('secure', True)), expires=expiry))
    result = normalize_credentials(result)
    current = value.get('currentUser') or next((unquote(c['value']) for c in result['cookies']
                                               if c['name'] == 'currentUser'), '')
    try:
        if isinstance(current, str):
            current = unquote(current.strip())
            user = json.loads(current) if current.startswith('{') else json.loads(base64.b64decode(current, validate=True))
        else: user = current
        if not isinstance(user, dict) or not all(isinstance(user.get(k), (str, int)) and str(user[k]) for k in ('username','userId')):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('缺少有效 currentUser：请从学校网站 Application → Local Storage 复制该项的值') from None
    try:
        parts = result['token'].split('.')
        if len(parts) != 3: raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        if str(claims['username']) != str(user['username']):
            raise ValueError()
        if float(claims['exp']) <= time.time() + 15:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError('Token 已过期或与 currentUser 账号不一致，请从同一次学校登录重新复制') from None
    # JWT claims only check consistency; the school API must validate the token before saving.
    result['currentUser'] = base64.b64encode(json.dumps(user, ensure_ascii=False).encode()).decode()
    if not result['userAgent']: result.pop('userAgent')
    result.pop('cookie', None)
    return result
