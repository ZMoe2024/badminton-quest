"""User-operated school login viewport. No credentials or URLs are sent to the UI."""
import base64
import queue
import time
from urllib.parse import urlsplit
from .browser_login import BrowserLogin, APP_HOST, SSO_HOST


class RemoteLogin(BrowserLogin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inputs = queue.Queue(maxsize=50)
        self.frame = None
        self.last_frame = 0

    def snapshot(self):
        result = super().snapshot()
        with self.guard:
            if result['active'] and self.frame:
                result['screen'] = self.frame
                result['screenWidth'], result['screenHeight'] = 1100, 760
        return result

    def start(self):
        if not self.snapshot()['active']:
            with self.guard:
                self.frame = None
                while not self.inputs.empty(): self.inputs.get_nowait()
        return super().start()

    def cancel(self):
        with self.guard:
            self.frame = None
        return super().cancel()

    def input(self, data):
        if not self.snapshot()['active']:
            raise ValueError('请先打开学校登录窗口')
        kind = data.get('kind')
        if kind == 'click':
            x, y = data.get('x'), data.get('y')
            if not isinstance(x, (float, int)) or not isinstance(y, (float, int)) or not 0 <= x < 1100 or not 0 <= y < 760:
                raise ValueError('点击位置无效')
            event = ('click', (x, y))
        elif kind == 'text':
            value = data.get('text')
            if not isinstance(value, str) or not 1 <= len(value) <= 256:
                raise ValueError('输入内容长度不正确')
            event = ('text', value)
        elif kind == 'key' and data.get('key') in ('Enter', 'Tab', 'Backspace', 'ArrowDown', 'ArrowUp'):
            event = ('key', data['key'])
        elif kind == 'scroll' and data.get('direction') in (-1, 1):
            event = ('scroll', data['direction'])
        else:
            raise ValueError('不支持的登录操作')
        try: self.inputs.put_nowait(event)
        except queue.Full: raise ValueError('输入过快，请稍候') from None
        return {'queued': True}

    def interact(self, pages):
        page = next((p for p in reversed(pages) if urlsplit(p.url).hostname in (APP_HOST, SSO_HOST)), None)
        if page is None:
            with self.guard: self.frame = None
            return
        from playwright.sync_api import Error
        try:
            if page.viewport_size != {'width': 1100, 'height': 760}:
                page.set_viewport_size({'width': 1100, 'height': 760})
            for _ in range(10):
                try: kind, value = self.inputs.get_nowait()
                except queue.Empty: break
                if kind == 'click': page.mouse.click(*value)
                elif kind == 'text': page.keyboard.insert_text(value)
                elif kind == 'key': page.keyboard.press(value)
                elif kind == 'scroll': page.mouse.wheel(0, value*450)
            if time.monotonic()-self.last_frame >= 0.8:
                encoded = base64.b64encode(page.screenshot(type='jpeg', quality=65, timeout=2500)).decode('ascii')
                with self.guard: self.frame = 'data:image/jpeg;base64,' + encoded
                self.last_frame = time.monotonic()
        except Error:
            # Redirecting pages can invalidate a frame; retry after the navigation.
            with self.guard: self.frame = None

    def _run(self):
        try: super()._run()
        finally:
            with self.guard:
                self.frame = None
                while not self.inputs.empty(): self.inputs.get_nowait()
