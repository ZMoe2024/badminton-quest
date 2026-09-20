"""Multi-user website entrypoint. Run one server instance per data directory."""
import argparse
import base64
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, redirect, request, send_from_directory
from .web_accounts import Accounts
from .web_workers import Workers

ROOT = Path(__file__).resolve().parent
COOKIE = 'quest_session'
PUBLIC = {'/app.js','/automation.js','/login.js','/style.css','/dashboard.css',
          '/assets/concept.png','/assets/gym.png'}
REMOTE = {'/web.css','/web.js','/auth.js','/login-helper.zip'}
ACTIONS = {'profile','save-profile','tasks','task-save','task-cancel','task-enable','orders',
           'save','session','renew','catalog','availability','records','check','book','order-status',
           'pay','import','login-status','login-cancel'}


def private_file(path, value):
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream: stream.write(value)
    return path.read_text(encoding='utf-8').strip()


def create_app(root, origin, *, workers=None, max_users=0, allow_insecure=False):
    root = Path(root).resolve();root.mkdir(mode=0o700, parents=True, exist_ok=True)
    parsed = urlsplit(origin)
    if (parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.query or
            parsed.fragment or parsed.username or parsed.password):
        raise ValueError('公开网址必须是完整来源，例如 https://quest.example.com，不含路径')
    if parsed.scheme != 'https' and parsed.hostname not in ('localhost','127.0.0.1') and not allow_insecure:
        raise ValueError('远程访问需要 HTTPS；仅局域网测试可明确指定 --allow-insecure-lan')
    key_file = root/'master.key'
    if not key_file.exists() and (root/'accounts.sqlite3').exists():
        raise ValueError('服务器密钥丢失，请恢复原 master.key；不会生成新密钥覆盖原数据')
    key = base64.urlsafe_b64decode(private_file(key_file, base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()))
    if len(key) != 32: raise ValueError('服务器密钥格式不正确')
    accounts = Accounts(root/'accounts.sqlite3', max_users)
    workers = workers or Workers(root, key, accounts)
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=100000, QUEST_ORIGIN=origin)
    app.extensions.update(quest_accounts=accounts, quest_workers=workers)

    @app.before_request
    def guard():
        # Railway probes use a different Host. Only this public, read-only path is exempt.
        if request.path == '/healthz' and request.method in ('GET', 'HEAD'):
            return None
        if request.host != parsed.netloc:
            return jsonify(error='访问地址不匹配，请使用部署时设置的网址'), 400
        if request.method == 'POST' and request.headers.get('Origin') != origin:
            return jsonify(error='请求来源校验失败'), 403
        g.user = accounts.session(request.cookies.get(COOKIE,''))
        if request.path.startswith('/api/'):
            if not g.user: return jsonify(error='网站登录已过期，请重新登录'), 401
            if request.method == 'POST' and not secrets.compare_digest(request.headers.get('X-Local-Token',''),g.user['csrf']):
                return jsonify(error='会话校验失败，请刷新页面'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if parsed.scheme == 'https': response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(413)
    def too_large(error): return jsonify(error='请求过大'), 413

    def data():
        value = request.get_json(silent=True)
        if not isinstance(value, dict): raise ValueError('请求格式错误')
        return value

    @app.get('/healthz')
    def health(): return jsonify(application='badminton-quest-web', status='ok')

    @app.get('/login')
    def login_page():
        if g.user: return redirect('/')
        return (ROOT/'web/login.html').read_text(encoding='utf-8')

    @app.post('/auth/<action>')
    def auth(action):
        if action not in ('login','register'): return jsonify(error='不存在'), 404
        ip=request.remote_addr or 'unknown'
        if not accounts.rate_limit('auth:'+ip, maximum=20) or not accounts.rate_limit('auth:all', maximum=120, seconds=60):
            return jsonify(error='尝试过多，请稍后再试'), 429
        try:
            body=data()
            name,password=body.get('username'),body.get('password')
            if action=='register':
                uid=accounts.register(name,password)
            else:
                uid=accounts.login(name,password)
                if not uid: return jsonify(error='用户名或密码不正确'), 401
            # Successful login rotates the current session.
            accounts.logout(request.cookies.get(COOKIE,''))
            response=jsonify(ok=True)
            response.set_cookie(COOKIE,accounts.issue(uid),max_age=7*86400,
                secure=parsed.scheme=='https',httponly=True,samesite='Strict',path='/')
            return response
        except ValueError as exc: return jsonify(error=str(exc)),400

    @app.post('/api/logout')
    def logout():
        # Website logout does not stop explicitly enabled background tasks.
        accounts.logout(request.cookies.get(COOKIE,''))
        try: workers.call(g.user['id'],{'action':'login-cancel'})
        except ValueError: pass  # Revoking a website session must not depend on a healthy worker.
        response=jsonify(ok=True);response.delete_cookie(COOKIE,path='/');return response

    @app.post('/api/password')
    def password():
        if not accounts.rate_limit('password:'+g.user['id'], maximum=6):return jsonify(error='尝试过多'),429
        try:
            body=data();accounts.change_password(g.user['id'],body.get('old'),body.get('new'))
            response=jsonify(ok=True);response.delete_cookie(COOKIE,path='/');return response
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.get('/')
    def index():
        if not g.user:return redirect('/login')
        html=(ROOT/'gui/index.html').read_text(encoding='utf-8')
        html=html.replace('__LOCAL_TOKEN__',g.user['csrf']).replace('</head>',
            '<meta name="quest-mode" content="web"><link rel="stylesheet" href="/web.css"><script src="/web.js" defer></script></head>')
        return html.replace('LOCAL EDITION · v0.5','WEB EDITION · 0.8')

    @app.get('/api/bootstrap')
    def bootstrap():
        try:
            status,value=workers.call(g.user['id'])
            if status==200:value.update(mode='web',websiteUser=g.user['name'])
            return jsonify(value),status
        except ValueError as exc:return jsonify(error=str(exc)),503

    @app.post('/api/action')
    def action():
        try:
            body=data();name=body.get('action')
            if not isinstance(name,str) or name not in ACTIONS:return jsonify(error='不支持的操作'),400
            uid=g.user['id']
            if name=='login-start' and not accounts.rate_limit('browser:'+uid, maximum=5, seconds=600):
                return jsonify(error='登录窗口开启过于频繁，请稍候'),429
            if not accounts.rate_limit('api:'+uid, maximum=240, seconds=60):return jsonify(error='操作过于频繁'),429
            status,value=workers.call(uid,body)
            return jsonify(value),status
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.get('/<path:name>')
    def assets(name):
        path='/'+name
        if path in PUBLIC:return send_from_directory(ROOT/'gui',name)
        if path in REMOTE:return send_from_directory(ROOT/'web',name)
        return jsonify(error='不存在'),404

    return app


def main():
    import signal
    def terminate(signum, frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    parser=argparse.ArgumentParser(description='羽球训练家 · 多用户网页版')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','18880')))
    parser.add_argument('--origin',default=os.environ.get('QUEST_ORIGIN') or
                        ('https://'+os.environ['RAILWAY_PUBLIC_DOMAIN'] if os.environ.get('RAILWAY_PUBLIC_DOMAIN') else None))
    parser.add_argument('--data',default=os.environ.get('QUEST_DATA','.quest-data'))
    parser.add_argument('--max-users',type=int,default=int(os.environ.get('QUEST_MAX_USERS','0')))
    parser.add_argument('--allow-insecure-lan',action='store_true')
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    if os.environ.get('RAILWAY_ENVIRONMENT_ID') and not os.environ.get('RAILWAY_VOLUME_MOUNT_PATH'):
        parser.error('请在 Railway 为服务挂载持久卷 /data，避免重启丢失账号和任务')
    if not 0<=args.max_users<=100000:parser.error('--max-users 必须为 0–100000，0 表示不限制注册人数')
    origin=args.origin or f'http://127.0.0.1:{args.port}'
    root=Path(args.data).resolve();root.mkdir(mode=0o700,parents=True,exist_ok=True)
    lease=(root/'server.lock').open('a+b')
    try:
        lease.seek(0);lease.write(b'0');lease.flush();lease.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lease.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:raise SystemExit('这份数据目录已有网页版后台在运行')
    app=create_app(root,origin,max_users=args.max_users,allow_insecure=args.allow_insecure_lan)
    workers=app.extensions['quest_workers']
    from waitress import create_server
    server=create_server(app,host=args.host,port=args.port,threads=16, max_request_body_size=100000,
                         expose_tracebacks=False,channel_timeout=200)
    print('羽球训练家网页版：'+origin,flush=True)
    print('公开注册已开启；学校会话由每位用户自行导入。',flush=True)
    print('按 Ctrl+C 停止；网站退出登录不会停止已启用任务。',flush=True)
    workers.start()
    if args.open:
        import webbrowser
        webbrowser.open(origin)
    try:server.run()
    except KeyboardInterrupt:pass
    finally:
        server.close();workers.close();lease.close()


if __name__=='__main__':main()
