"""One isolated execution process per website account, with loopback-only RPC."""
import base64
import hashlib
import hmac
import multiprocessing
import os
from pathlib import Path
import re
import threading
import time
import requests


def worker_main(connection, directory, key, database, uid, stop):
    os.environ['BADMINTON_DATA_DIR'] = directory
    os.environ['BADMINTON_SERVER_KEY'] = key
    from .runtime import initialize_user
    initialize_user(directory)
    from . import gui_server
    from .web_credentials import prepare_credentials
    from .web_accounts import Accounts
    from .web_rentals import Rentals
    from . import rental_worker
    accounts = Accounts(database)
    rentals = Rentals(accounts)

    class UserApplication(gui_server.Application):
        def __init__(self):
            super().__init__()
            self.browser_login._status('idle', '请在下方导入自己的学校登录凭据。')

        def save_login(self, credentials, status):
            # Bind to the token-checked username, not editable userId metadata.
            username, _ = gui_server.expected_identity(credentials)
            identity = hashlib.sha256(username.encode()).hexdigest()
            with accounts.school_binding(uid, identity):
                super().save_login(credentials, status)

        def action(self, data):
            # Internal RPC only: deliberately excluded from public /api/action.
            if data.get('action') == 'rental-ready':
                rental_worker.ready(rentals, uid, self)
                return {'ready': True}
            if data.get('action') == 'rental-slots':
                return rental_worker.slots(rentals, uid, self, data['offerId'], data['config'])
            if data.get('action') in ('rental-run', 'rental-check'):
                operation = rental_worker.execute if data['action'] == 'rental-run' else rental_worker.reconcile
                operation(rentals, uid, self, data['id'])
                return {'ok': True}
            if data.get('action') in ('login-start', 'login-input'):
                raise ValueError('网页版使用手动导入会话，请在登录设置填写自己的凭据')
            if data.get('action') == 'import':
                data = dict(data, credentials=prepare_credentials(data.get('credentials')))
                result = super().action(data)
                username, _ = gui_server.expected_identity(data['credentials'])
                self.browser_login._status('success', '会话已验证并加密保存；可以刷新实时场地。',
                    account=username[:2]+'****'+username[-2:],
                    ssoAvailable=bool(data['credentials'].get('ssoCookies')))
                return result
            return super().action(data)

        def confirm_once(self, data):
            if data.get('confirmed') is not True:
                raise ValueError('请在确认窗口中核对后提交')
            accounts.claim_request(uid, data.get('requestId'))

    app = UserApplication()
    server = gui_server.LocalServer(('127.0.0.1', 0), gui_server.make_handler(app))
    server.timeout = .5
    app.scheduler.start()
    if app.scheduler.fatal:
        server.server_close()
        connection.close()
        return
    connection.send({'port': server.server_port, 'token': app.token})
    connection.close()
    # Keep cancellation/status available while a network operation is running.
    try:
        parent = multiprocessing.parent_process()
        while not stop.is_set() and (parent is None or parent.is_alive()): server.handle_request()
    finally:
        app.browser_login.cancel()
        if app.browser_login.thread: app.browser_login.thread.join(timeout=50)
        app.scheduler.stop_event.set()
        if app.scheduler.thread: app.scheduler.thread.join(timeout=35)
        server.server_close()


class Workers:
    def __init__(self, root, master_key, accounts):
        self.root = Path(root)
        self.key = master_key
        self.accounts = accounts
        self.workers = {}
        self.guard = threading.Lock()
        self.login_guard = threading.Lock()
        self.login_owner = None
        self.ctx = multiprocessing.get_context('spawn')
        self.stopping = threading.Event()
        self.monitor = None

    def get(self, uid):
        if not re.fullmatch('[0-9a-f]{32}', uid): raise ValueError('网站账号编号无效')
        with self.guard:
            existing = self.workers.get(uid)
            if existing and existing['process'].is_alive(): return existing
            if existing:
                existing['process'].join(timeout=1)
                if time.monotonic()-existing['started'] < 10:
                    raise ValueError('该账号后台启动失败，请检查服务器浏览器和数据目录')
            receive, send = self.ctx.Pipe(duplex=False)
            key = base64.urlsafe_b64encode(hmac.new(self.key, uid.encode(), hashlib.sha256).digest()).decode()
            stop = self.ctx.Event()
            process = self.ctx.Process(target=worker_main, args=(send, str(self.root/'users'/uid),
                key, str(self.accounts.path), uid, stop), name='quest-'+uid[:8])
            process.start()
            send.close()
            if not receive.poll(20):
                stop.set();process.terminate();process.join(5);receive.close()
                raise ValueError('账号后台启动超时，请稍后重试')
            try: config = receive.recv()
            except EOFError:
                process.join(2)
                raise ValueError('账号后台启动失败，请检查服务器日志') from None
            finally: receive.close()
            item = dict(config, process=process, stop=stop, started=time.monotonic())
            self.workers[uid] = item
            return item

    def call(self, uid, action=None):
        if action and action.get('action') == 'login-start':
            # Serialize browser launches on small hosts; booking workers remain independent.
            with self.login_guard:
                if self.login_owner and self.login_owner != uid:
                    status, state = self._call(self.login_owner, {'action':'login-status'})
                    if status != 200 or state.get('active'):
                        return 409, {'error':'另一位用户正在登录学校，请稍后再打开登录窗口'}
                status, state = self._call(uid, action)
                if status == 200 and state.get('active'): self.login_owner = uid
                return status, state
        return self._call(uid, action)

    def _call(self, uid, action=None):
        item = self.get(uid)
        base = 'http://127.0.0.1:' + str(item['port'])
        try:
            # No inherited proxy may forward internal RPC or user credentials.
            with requests.Session() as http:
                http.trust_env = False
                if action is None: response = http.get(base+'/api/bootstrap', timeout=10)
                else: response = http.post(base+'/api/action', json=action,
                    headers={'Origin': base, 'X-Local-Token': item['token']}, timeout=(5, 180))
            return response.status_code, response.json()
        except (requests.RequestException, ValueError):
            return 503, {'error': '后台连接中断；若已提交预约或付款，请先查询原记录，勿重复提交。'}

    def resume(self):
        # Restore execution after a restart, even when no browser is connected.
        import json
        active = {'waiting','checking','submitting','paying','unknown','payment_pending','needs_login'}
        for uid in self.accounts.ids():
            path = self.root/'users'/uid/'state/automation/tasks.json'
            if path.exists():
                try:
                    jobs = json.loads(path.read_text(encoding='utf-8'))['jobs']
                    if any(job.get('state') in active for job in jobs.values()): self.get(uid)
                except (ValueError, OSError, KeyError):
                    # Don't rewrite corrupt task files or erase indeterminate orders.
                    continue

    def start(self):
        self.resume()
        def monitor():
            while not self.stopping.wait(5):
                with self.guard: dead = [uid for uid,item in self.workers.items() if not item['process'].is_alive()]
                for uid in dead:
                    try: self.get(uid)
                    except ValueError: pass
        self.monitor = threading.Thread(target=monitor, daemon=True, name='user-worker-monitor')
        self.monitor.start()

    def close(self):
        self.stopping.set()
        if self.monitor: self.monitor.join(timeout=25)
        with self.guard: items = list(self.workers.values())
        for item in items: item['stop'].set()
        deadline = time.monotonic()+90
        for item in items:
            item['process'].join(timeout=max(0, deadline-time.monotonic()))
            if item['process'].is_alive(): item['process'].terminate();item['process'].join(5)
