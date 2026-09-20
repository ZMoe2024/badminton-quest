"""Loopback-only GUI host. No browser credentials are exposed to the frontend."""
import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import secrets
import socket
import threading
import time
import webbrowser
from urllib.request import urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from . import session_store
from . import __version__
from .badminton import CATALOG, refresh
from .badminton_booking import resolve
from .availability import fetch_availability, now_local
from .workflow import authenticate, book, DEFAULT_SESSION, DEFAULT_CONFIG
from .resm_api import ResourceAPI
from .payment import pay, DETAIL_PATH, resolve_order
from .session import expected_identity
from .automation import Scheduler
from .browser_login import BrowserLogin
from .booking_profile import load_phone, save_phone, require_phone

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'gui'


def catalog():
    rows = json.loads(CATALOG.read_text(encoding='utf-8'))['courts']
    for row in rows:
        row['group'] = 'main' if '主馆羽毛球' in row['name'] else ('tianyou' if '天佑' in row['location'] else 'annex')
    return rows


def safe_error(exc):
    return str(exc) if isinstance(exc, ValueError) else '请求未完成，请核实记录后再操作。不会自动重新预约或支付。'


def list_orders():
    result = []
    for path in sorted((ROOT / 'state/orders').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
            if all(k in d for k in ('feeOrderId', 'occupyId', 'infoId', 'expectedAmount', 'start', 'end')):
                result.append(dict(d, key=path.stem))
        except (ValueError, OSError): pass
    return result


def read_order(key):
    if not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('订单引用无效')
    return json.loads((ROOT / 'state/orders' / (key + '.json')).read_text(encoding='utf-8'))


def records(credentials, date):
    dt.date.fromisoformat(date)
    c = ResourceAPI(credentials)
    try:
        params = {'limit': 100, 'offset': 1, 'searchStartTime': date + ' 00:00:00',
                  'searchEndTime': date + ' 23:59:59', 'recordStatus': '',
                  'orderByField': 'recordTimeStart,recordCreateDate,occupyId', 'orderByFlag': 'desc'}
        d = c.query('/hzsun-resm/subUseRecord/queryReservationRecord', params)
        keys = ('infoName', 'infoId', 'occupyId', 'recordTimeStart', 'recordTimeEnd', 'recordUseStatus', 'feePayStatus')
        return {'total': d['total'], 'rows': [{k: r.get(k) for k in keys} for r in d['rows']]}
    finally: c.close()


class Application:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.seen = set()
        self.scheduler = Scheduler(self.lock)
        self.browser_login = BrowserLogin(self.lock,
            lambda credentials: authenticate(credentials=credentials), self.save_login)

    def save_login(self, credentials, status):
        self.scheduler.assert_session_compatible(credentials)
        session_store.save(DEFAULT_SESSION, credentials)
        self.scheduler.note_health(status)

    def boot(self):
        return {'courts': catalog(), 'config': json.loads(DEFAULT_CONFIG.read_text(encoding='utf-8')),
                'today': now_local().date().isoformat(), 'sessionStored': DEFAULT_SESSION.exists(),
                'version': __version__, 'application': 'badminton-quest'}

    def action(self, data):
        action = data.get('action')
        if action == 'login-start': return self.browser_login.start()
        if action == 'login-status': return self.browser_login.snapshot()
        if action == 'login-cancel': return self.browser_login.cancel()
        if action == 'profile': return {'phone': load_phone()}
        if action == 'save-profile':
            save_phone(data.get('phone'))
            return {'saved': True}
        if action in ('task-enable', 'book', 'check'): require_phone()
        if action in ('availability', 'catalog', 'check') and self.scheduler.due_soon():
            raise ValueError('自动预约即将查询或提交，暂缓手动刷新，请在任务页查看进度')
        if action == 'tasks': return self.scheduler.snapshot()
        if action == 'task-save':
            job = self.scheduler.save_draft(data['config'], data.get('id'))
            return {'id': job['id']}
        if action == 'task-cancel': return self.scheduler.cancel(data.get('id'))
        if action == 'task-enable':
            self.confirm_once(data)
            credentials, status = authenticate()
            self.scheduler.note_health(status)
            return self.scheduler.enable(data['id'], credentials)
        if action == 'orders': return {'orders': list_orders()}
        if action == 'save':
            cfg = data['config']; resolve(cfg)
            DEFAULT_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
            return {'saved': True}
        if action == 'import':
            credentials = data.get('credentials')
            if not isinstance(credentials, dict): raise ValueError('请导入有效的登录凭据 JSON')
            verified, status = authenticate(credentials=credentials)
            self.save_login(verified, status)
            return {'authentication': status}
        try:
            credentials, status = authenticate(force_renew=action == 'renew')
        except Exception as exc:
            self.scheduler.note_health(error=exc)
            raise
        if action in ('session', 'renew'):
            self.scheduler.note_health(status)
            username, _ = expected_identity(credentials)
            return {'authentication': status, 'account': username[:2] + '****' + username[-2:]}
        if action == 'catalog':
            refresh(credentials)
            return {'courts': catalog(), 'fetchedAt': dt.datetime.now().isoformat()}
        if action == 'availability':
            rows = [r for r in catalog() if r['group'] == data.get('group')]
            if not rows: raise ValueError('未找到羽毛球场馆')
            return fetch_availability(credentials, rows, data['date'])
        if action == 'records': return records(credentials, data['date'])
        if action in ('check', 'book'):
            cfg = data['config']; row, date, start, end = resolve(cfg)
            fresh = fetch_availability(credentials, [row], date)
            slots = fresh['courts'][0]['slots']
            selected = next((s for s in slots if s['start'] == start and s['end'] == end), None)
            if selected is None or not selected['available']:
                raise ValueError('网站最新状态不可预约或未能核实，请刷新时段。')
            if action == 'check': return book(cfg, credentials=credentials)
            self.confirm_once(data)
            result = book(cfg, submit=True, pay_after=data.get('pay') is True, credentials=credentials)
            folder = ROOT / 'state/gui'; folder.mkdir(exist_ok=True, parents=True)
            (folder / (str(time.time_ns()) + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            return result
        if action in ('order-status', 'pay'):
            cfg = read_order(data.get('key'))
            if action == 'pay':
                self.confirm_once(data)
                return {'payment': pay(credentials, cfg, submit=True)}
            _, uid = expected_identity(credentials)
            c = ResourceAPI(credentials)
            try:
                d = c.query(DETAIL_PATH, {'infoId': cfg['infoId'], 'occupyId': cfg['occupyId'], 'userId': uid})
                if not isinstance(d, dict) or d.get('feeOrderId') != cfg['feeOrderId']: raise ValueError('订单不匹配')
                return {k: d.get(k) for k in ('infoName', 'feeOrderId', 'feePayStatus', 'feeOrderStatus', 'feeOrderAmount', 'feeOrderExpiredDate')}
            finally: c.close()
        raise ValueError('不支持的操作')

    def confirm_once(self, data):
        request_id = data.get('requestId')
        if data.get('confirmed') is not True or not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
            raise ValueError('请在确认窗口中核对后提交')
        if request_id in self.seen: raise ValueError('这个操作已经提交，请核实结果，不重复发送')
        self.seen.add(request_id)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            raw = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, dict) else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError): pass

        def valid_host(self):
            return self.headers.get('Host') == '127.0.0.1:' + str(self.server.server_port)

        def do_GET(self):
            if not self.valid_host(): return self.send(403, {'error': '仅支持本机访问'})
            path = urlsplit(self.path).path
            if path == '/api/bootstrap': return self.send(200, app.boot())
            if path == '/':
                html = (WEB / 'index.html').read_text(encoding='utf-8').replace('__LOCAL_TOKEN__', app.token)
                return self.send(200, html.encode(), 'text/html; charset=utf-8')
            allowed = {'/app.js', '/automation.js', '/login.js', '/style.css', '/dashboard.css', '/assets/concept.png', '/assets/gym.png'}
            if path not in allowed: return self.send(404, {'error': '不存在'})
            file = WEB / path.lstrip('/')
            self.send(200, file.read_bytes(), mimetypes.guess_type(str(file))[0] or 'application/octet-stream')

        def do_POST(self):
            origin = 'http://127.0.0.1:' + str(self.server.server_port)
            if not self.valid_host() or self.headers.get('Origin') != origin or not secrets.compare_digest(self.headers.get('X-Local-Token', ''), app.token):
                return self.send(403, {'error': '本地会话校验失败，请从启动器打开界面'})
            if self.path != '/api/action': return self.send(404, {'error': '不存在'})
            acquired = False
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length < 100000: raise ValueError('请求大小不正确')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict): raise ValueError('请求格式错误')
                if data.get('action') not in ('tasks', 'task-save', 'task-cancel', 'login-start', 'login-status', 'login-cancel'):
                    acquired = app.lock.acquire(blocking=False)
                    if not acquired: return self.send(409, {'error': '后台正在查询或处理任务，请稍候再试'})
                self.send(200, app.action(data))
            except Exception as exc: self.send(400, {'error': safe_error(exc)})
            finally:
                if acquired: app.lock.release()
    return Handler


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    parser = argparse.ArgumentParser(description='羽球训练家 · 本地 GUI')
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    try:
        server = LocalServer(('127.0.0.1', args.port), BaseHTTPRequestHandler)
    except OSError:
        with urlopen(url + '/api/bootstrap', timeout=3) as response:
            existing = json.load(response)
            if existing.get('application') != 'badminton-quest':
                raise RuntimeError('端口被其他程序占用，请使用 --port 指定另一个端口')
            if existing.get('version') != __version__:
                raise RuntimeError('旧版羽球训练家仍在运行，请先退出旧版后台，再启动新版本；不会自动打开旧界面。')
        if not args.no_open: webbrowser.open(url)
        return
    app = Application()
    server.RequestHandlerClass = make_handler(app)
    print('羽球训练家 ' + url, flush=True)
    app.scheduler.start()
    if not args.no_open: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        app.browser_login.cancel()
        app.scheduler.stop_event.set()
        server.server_close()


if __name__ == '__main__': main()
