"""Renew the application token through an existing CAS session, without credentials entry."""
import base64
import copy
import json
from urllib.parse import parse_qs, urljoin, urlsplit, urlencode
import requests
from .ecn_client import ORIGIN
from .resm_api import ResourceAPI, encode_business
from .response import decode_result

CAS_HOST = 'authserver.lzjtu.edu.cn'
SERVICE = ORIGIN + '/static/cas.html'


class LoginRequired(ValueError):
    pass


def cookie_rows(jar):
    return [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path,
             'secure': c.secure, 'expires': c.expires} for c in jar]


def expected_identity(inputs):
    try:
        user = json.loads(base64.b64decode(inputs['currentUser']).decode('utf-8'))
        return str(user['username']), str(user['userId'])
    except (KeyError, ValueError, TypeError):
        raise ValueError('自动续期需要原 currentUser，用于确认续期前后的账号一致') from None


def acquire_ticket(inputs):
    if not inputs.get('ssoCookies'):
        raise LoginRequired('缺少学校统一认证会话；需要先导入当前学校登录会话')
    session = requests.Session()
    session.headers['User-Agent'] = inputs.get('userAgent', 'Mozilla/5.0')
    for c in inputs['ssoCookies']:
        if c['domain'].lstrip('.') in (CAS_HOST, 'lzjtu.edu.cn'):
            session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'],
                                secure=c.get('secure', False),
                                expires=c['expires'] if (c.get('expires') or 0) > 0 else None)
    try:
        url, params = f'https://{CAS_HOST}/authserver/login', {'service': SERVICE, 'gateway': 'true'}
        for _ in range(6):
            response = session.get(url, params=params, timeout=25, allow_redirects=False)
            if response.status_code not in (301, 302, 303, 307, 308) or not response.headers.get('Location'):
                raise LoginRequired('学校认证未静默签发票据，需要重新完成学校登录')
            target = urljoin(url, response.headers['Location'])
            parsed = urlsplit(target)
            if parsed.scheme != 'https' or parsed.username or parsed.password:
                raise LoginRequired('认证跳转不符合已验证的HTTPS流程')
            if parsed.netloc == 'resm.lzjtu.edu.cn' and parsed.path == '/static/cas.html':
                ticket = parse_qs(parsed.query).get('ticket', parse_qs(parsed.query).get('st', []))
                if not ticket or len(ticket) != 1:
                    raise LoginRequired('学校登录会话已不能静默签发票据，需要重新登录')
                return ticket[0], cookie_rows(session.cookies)
            if parsed.netloc != CAS_HOST:
                raise LoginRequired('学校认证跳转到新的入口，需要核对流程')
            url, params = target, None
        raise LoginRequired('学校认证跳转次数异常，停止自动续期')
    finally:
        session.close()


def renew(inputs):
    identity = expected_identity(inputs)
    ticket, sso_cookies = acquire_ticket(inputs)
    client = ResourceAPI(inputs)
    try:
        query = urlencode({k: encode_business(v) for k, v in {'ticket': ticket, 'service': SERVICE}.items()})
        response = client.get('/hzsun-resm/cas/client/validateLogin?' + query)
        # CAS returns the login object directly, unlike ordinary errCode/responseResult APIs.
        result = decode_result(response.text)
        if response.status_code != 200:
            raise LoginRequired('登录票据兑换失败')
        if not isinstance(result, dict):
            raise LoginRequired('登录票据兑换返回格式变化')
        token = result.get('token')
        user = result.get('sysUser') or result.get('userInfo')
        if not token or not isinstance(user, dict):
            raise LoginRequired('登录票据兑换未返回Token或用户信息')
        if (str(user.get('username')), str(user.get('userId'))) != identity:
            raise LoginRequired('续期后的学校账号与原预约账号不一致，停止使用')
        refreshed = copy.deepcopy(inputs)
        refreshed.pop('cookie', None)
        refreshed['token'] = token
        refreshed['currentUser'] = base64.b64encode(json.dumps(user, ensure_ascii=False).encode()).decode()
        refreshed['cookies'] = cookie_rows(client.session.cookies)
        for c in refreshed['cookies']:
            if c['name'] == 'token': c['value'] = token
        refreshed['ssoCookies'] = sso_cookies
        return refreshed
    finally:
        client.close()


def probe(inputs):
    client = ResourceAPI(inputs)
    try:
        response = client.get('/hzsun-resm/msg/unReadCounts')
        result = decode_result(response.text)
        code = str(result.get('errCode')) if isinstance(result, dict) else None
        updated = copy.deepcopy(inputs)
        updated.pop('cookie', None)
        updated['token'] = client.credentials['token']
        updated['cookies'] = cookie_rows(client.session.cookies)
        if response.status_code == 200 and code == '0000':
            return updated, True
        if response.status_code == 401 or code == '401':
            return updated, False
        raise ValueError(f'会话检查未通过：HTTP {response.status_code}，业务码 {code}；不将网络或防护错误当作登录过期')
    finally:
        client.close()


def ensure_session(inputs, force_renew=False):
    updated = inputs
    if not force_renew:
        updated, valid = probe(inputs)
        if valid:
            return updated, {'valid': True, 'renewed': False, 'ssoAvailable': bool(updated.get('ssoCookies'))}
    updated = renew(updated)
    updated, valid = probe(updated)
    if not valid:
        raise LoginRequired('新Token仍未通过会话校验，需要重新登录')
    return updated, {'valid': True, 'renewed': True, 'ssoAvailable': True}
