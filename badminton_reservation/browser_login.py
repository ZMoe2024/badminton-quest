"""Interactive, isolated login capture. Browser data never reaches the GUI API."""
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit

from .session import expected_identity

APP_ORIGIN = 'https://resm.lzjtu.edu.cn'
APP_HOST = 'resm.lzjtu.edu.cn'
SSO_HOST = 'authserver.lzjtu.edu.cn'
# Enter through the application so its ordinary browser initialization runs
# before CAS redirects back with a one-use ticket.
LOGIN_URL = APP_ORIGIN + '/'
ACTIVE = {'opening', 'waiting', 'verifying', 'cancelling'}


def app_url(url):
    value = urlsplit(url)
    return value.scheme == 'https' and value.netloc == APP_HOST


def select_cookies(rows, host):
    allowed = {host, 'lzjtu.edu.cn'}
    return [{key: row[key] for key in ('name', 'value', 'domain', 'path', 'secure', 'expires') if key in row}
            for row in rows if row.get('domain', '').lstrip('.') in allowed]


def collect_credentials(storage, tokens, cookies, now=None):
    """Select only matching, unexpired identity material; server verification follows."""
    current = storage.get('currentUser')
    if not current:
        return None
    try:
        username, user_id = expected_identity({'currentUser': current})
    except ValueError:
        return None
    if username in ('', 'None') or user_id in ('', 'None'):
        return None
    app_cookies = select_cookies(cookies, APP_HOST)
    if not app_cookies:
        return None
    candidates = list(tokens)[::-1] + [storage.get('token')] + [
        unquote(c['value']) for c in app_cookies if c['name'] == 'token']
    for token in candidates:
        try:
            if not isinstance(token, str) or len(token) > 20000:
                continue
            part = token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
            if str(claims.get('username')) != username or float(claims.get('exp', 0)) <= (now or time.time()) + 15:
                continue
        except (ValueError, IndexError, TypeError):
            continue
        return {'token': token, 'currentUser': current, 'cookies': app_cookies,
                'ssoCookies': select_cookies(cookies, SSO_HOST),
                'userAgent': storage.get('userAgent', 'Mozilla/5.0')}
    return None


class LoginCancelled(Exception):
    pass


class LoginBrowser:
    """Own one regular browser process and disposable profile, never a personal one."""
    def __init__(self):
        self.process = None
        self.browser = None
        self.profile = None

    def open(self, playwright, check):
        from playwright.sync_api import Error
        if sys.platform == 'win32':
            candidates = [Path(os.environ.get(root, 'C:/')) / 'Google/Chrome/Application/chrome.exe'
                          for root in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        elif sys.platform == 'darwin':
            candidates = [Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
                          Path.home() / 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
        else:
            candidates = [Path(value) for name in ('google-chrome', 'chromium', 'chromium-browser')
                          if (value := shutil.which(name))]
        candidates.append(Path(playwright.chromium.executable_path))
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            raise ValueError('未找到登录浏览器。请关闭程序后使用 Start 启动器重启，自动安装 Chromium。')
        self.profile = Path(tempfile.mkdtemp(prefix='badminton-login-')).resolve()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        extra = ['--disable-dev-shm-usage'] if os.environ.get('RAILWAY_ENVIRONMENT_ID') else []
        self.process = subprocess.Popen([
            str(executable), '--remote-debugging-address=127.0.0.1',
            '--remote-debugging-port=' + str(port), '--user-data-dir=' + str(self.profile),
            '--no-first-run', '--no-default-browser-check', '--window-size=1120,800', *extra, 'about:blank'
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            check()
            if self.process.poll() is not None:
                raise ValueError('独立登录浏览器已关闭，请重新点击登录。')
            try:
                self.browser = playwright.chromium.connect_over_cdp('http://127.0.0.1:' + str(port), timeout=1000)
                return self.browser, self.browser.contexts[0]
            except Error:
                time.sleep(0.1)
        raise ValueError('独立登录浏览器连接超时，原会话保留。')

    def close(self):
        if self.browser is not None:
            try:
                # Closing a CDP connection alone can leave Chrome and its cookies on disk.
                self.browser.new_browser_cdp_session().send('Browser.close')
            except Exception:
                pass
            try:
                self.browser.close()
            except Exception:
                pass
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        # Only remove the exact temporary directory created by this instance.
        if (self.profile is not None and self.profile.parent == Path(tempfile.gettempdir()).resolve()
                and self.profile.name.startswith('badminton-login-')):
            for _ in range(20):
                try:
                    shutil.rmtree(self.profile)
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(0.1)


class BrowserLogin:
    def __init__(self, network_lock, verify, save, timeout=600):
        self.network_lock = network_lock
        self.verify = verify
        self.save = save
        self.timeout = timeout
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.status = {'state': 'idle', 'message': '点击登录学校账号，在独立窗口完成认证。'}

    def snapshot(self):
        with self.guard:
            return dict(self.status, active=bool(self.thread and self.thread.is_alive()))

    def _status(self, state, message, **fields):
        with self.guard:
            self.status = dict(state=state, message=message, **fields)

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return self.snapshot()
            self.stop = threading.Event()
            self._status('opening', '正在打开独立登录窗口，请在窗口中使用自己的学校账号。')
            self.thread = threading.Thread(target=self._run, name='school-login', daemon=True)
            self.thread.start()
            return self.snapshot()

    def cancel(self):
        with self.guard:
            if self.thread and self.thread.is_alive() and self.status['state'] in ACTIVE:
                self.stop.set()
                self._status('cancelling', '正在取消；未保存的登录资料会丢弃，原会话保留。')
            return self.snapshot()

    def _check(self, deadline):
        if self.stop.is_set():
            raise LoginCancelled()
        if time.monotonic() >= deadline:
            raise ValueError('登录等待已超时，原会话保留。请重新点击登录。')

    def interact(self, pages):
        """Optional server-side login viewport; local mode has no remote controls."""
        pass

    def _accept(self, credentials, deadline, check_page=None):
        self._status('verifying', '已识别学校账号，正在用 Python 验证会话并加密保存…')
        acquired = False
        try:
            while not acquired:
                self._check(deadline)
                acquired = self.network_lock.acquire(timeout=0.25)
            self._check(deadline)
            updated, status = self.verify(credentials)
            if expected_identity(updated) != expected_identity(credentials):
                raise ValueError('验证前后学校账号不一致，原会话保留，请重新登录。')
            if check_page is not None:
                check_page()
            with self.guard:
                self._check(deadline)
                self.save(updated, status)
                username, _ = expected_identity(updated)
                self._status('success', '登录成功，凭据已加密保存；可以回到场地探索刷新。',
                             account=username[:2] + '****' + username[-2:],
                             ssoAvailable=bool(updated.get('ssoCookies')))
        finally:
            if acquired:
                self.network_lock.release()

    def _run(self):
        browser = None
        owned = LoginBrowser()
        try:
            from playwright.sync_api import sync_playwright, Error
            deadline = time.monotonic() + self.timeout
            with sync_playwright() as playwright:
                context = None
                try:
                    browser, context = owned.open(playwright, lambda: self._check(deadline))
                    tokens = []

                    def on_request(request):
                        if app_url(request.url):
                            try:
                                token = request.header_value('x-access-token')
                            except Error:
                                return
                            if token and token not in tokens:
                                tokens.append(token)
                                del tokens[:-8]

                    context.on('request', on_request)
                    page = context.pages[0] if context.pages else context.new_page()
                    document_status = {}

                    def on_response(response):
                        if response.request.resource_type == 'document':
                            parsed = urlsplit(response.url)
                            if parsed.hostname in (APP_HOST, SSO_HOST):
                                document_status[(parsed.hostname, parsed.path)] = response.status

                    context.on('response', on_response)
                    try:
                        page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=45000)
                    except Error:
                        if not browser.is_connected():
                            raise LoginCancelled() from None
                        # Login redirects can abort the original navigation. Inspect the live pages.
                        if page.url == 'about:blank':
                            failed = next((value for value in reversed(list(document_status.values())) if value >= 400), None)
                            if failed is not None:
                                raise ValueError(f'学校登录页面返回 HTTP {failed}，原会话保留。请重新登录或检查学校网站访问情况。') from None
                            raise ValueError('学校统一认证页面未能打开，请检查网络后重新点击登录。') from None
                    self._status('waiting', '请在统一认证窗口扫码或使用自己的学校账号登录，返回预约网站后会自动识别。')
                    blank_since = None
                    while True:
                        self._check(deadline)
                        pages = [p for p in context.pages if not p.is_closed()]
                        if not browser.is_connected() or not pages:
                            raise LoginCancelled()
                        self.interact(pages)
                        # A failed protection/navigation response must not look like an endless login wait.
                        blank_failure = None
                        for current in pages:
                            parsed = urlsplit(current.url)
                            if parsed.scheme == 'chrome-error':
                                blank_failure = next((status for status in reversed(list(document_status.values())) if status >= 400), None)
                                if blank_failure is None:
                                    raise ValueError('学校登录页面加载失败，请检查网络或学校网站访问情况；原会话保留。')
                                continue
                            code = document_status.get((parsed.hostname, parsed.path))
                            if parsed.hostname not in (APP_HOST, SSO_HOST):
                                continue
                            try:
                                empty = current.evaluate("() => !document.body || !document.querySelector('input:not([type=hidden]),iframe,canvas')")
                            except Error:
                                continue
                            if empty and code is not None and code >= 400:
                                blank_failure = code
                        if blank_failure is not None:
                            blank_since = blank_since or time.monotonic()
                            if time.monotonic() - blank_since >= 8:
                                raise ValueError(f'学校页面返回 HTTP {blank_failure} 且未显示可用的登录界面；原会话保留。请重新登录或检查学校网站访问情况。')
                        else:
                            blank_since = None
                        for current in pages:
                            if not app_url(current.url):
                                continue
                            try:
                                storage = current.evaluate('''() => ({
                                    currentUser: sessionStorage.getItem('currentUser'),
                                    token: sessionStorage.getItem('token') || localStorage.getItem('token'),
                                    userAgent: navigator.userAgent
                                })''')
                                credentials = collect_credentials(storage, tokens, context.cookies())
                            except Error:
                                continue
                            if credentials:
                                def check_page():
                                    live_user = current.evaluate("() => sessionStorage.getItem('currentUser')")
                                    if live_user != credentials['currentUser']:
                                        raise ValueError('验证期间登录页面的账号发生变化，请重新登录；原会话保留。')
                                self._accept(credentials, deadline, check_page)
                                return
                        # Playwright pumps request/page events during this wait.
                        pages[0].wait_for_timeout(500)
                except Error:
                    if self.stop.is_set() or (browser is not None and not browser.is_connected()) or (context is not None and not context.pages):
                        raise LoginCancelled() from None
                    raise
                finally:
                    owned.close()
        except LoginCancelled:
            self._status('cancelled', '登录已取消，原会话保留。')
        except ImportError:
            self._status('error', '登录组件未安装，请使用 Start 启动器重启以安装依赖。')
        except Exception as exc:
            # Browser errors can contain URLs, tickets and headers. Never expose them.
            message = str(exc) if isinstance(exc, ValueError) else '登录窗口或网络连接失败，原会话保留，请重试。'
            self._status('cancelled' if self.stop.is_set() else 'error',
                         '登录已取消，原会话保留。' if self.stop.is_set() else message)
