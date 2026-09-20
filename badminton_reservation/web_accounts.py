"""Website accounts, revocable sessions and durable replay protection."""
import hashlib
import secrets
import sqlite3
import time
import uuid
import re
from contextlib import contextmanager
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Accounts:
    def __init__(self, path, limit=16):
        self.path = Path(path)
        self.limit = limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
                    school TEXT UNIQUE, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (bucket TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS attempts_bucket ON attempts(bucket, at);
                CREATE TABLE IF NOT EXISTS requests (
                    user_id TEXT NOT NULL, request_id TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(user_id, request_id));
            ''')
        # Same-cost password check for missing users.
        self.dummy = generate_password_hash(secrets.token_urlsafe(24))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def rate_limit(self, bucket, maximum=10, seconds=900):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE at < ?', (now - 86400,))
            count = db.execute('SELECT count(*) FROM attempts WHERE bucket=? AND at>?',
                               (bucket, now-seconds)).fetchone()[0]
            if count >= maximum:
                return False
            db.execute('INSERT INTO attempts VALUES (?,?)', (bucket, now))
        return True

    def register(self, name, password):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,32}', name):
            raise ValueError('用户名须为 3–32 位字母、数字、下划线或短横线')
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise ValueError('密码须为 10–128 个字符')
        hashed = generate_password_hash(password)
        uid = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT count(*) FROM users').fetchone()[0] >= self.limit:
                    raise ValueError('本站用户数量已达上限，请联系部署者')
                db.execute('INSERT INTO users(id,name,password,created) VALUES(?,?,?,?)',
                           (uid, name.lower(), hashed, time.time()))
        except sqlite3.IntegrityError:
            raise ValueError('这个用户名不可用') from None
        return uid

    def login(self, name, password):
        if not isinstance(name, str) or not isinstance(password, str) or len(password) > 128:
            return None
        with self.connect() as db:
            row = db.execute('SELECT id,password FROM users WHERE name=?', (name.lower(),)).fetchone()
        valid = check_password_hash(row['password'] if row else self.dummy, password)
        return row['id'] if row and valid else None

    def issue(self, uid):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), uid, csrf, time.time()+7*86400))
        return token

    def session(self, token):
        with self.connect() as db:
            row = db.execute('''SELECT u.id,u.name,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token=? AND s.expires>?''', (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

    def change_password(self, uid, old, new):
        if not isinstance(old, str) or not isinstance(new, str) or not 10 <= len(new) <= 128 or len(old)>128:
            raise ValueError('请填写原密码以及 10–128 个字符的新密码')
        with self.connect() as db:
            row = db.execute('SELECT password FROM users WHERE id=?', (uid,)).fetchone()
            if not row or not check_password_hash(row['password'], old):
                raise ValueError('原密码不正确')
            db.execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(new), uid))
            db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))

    def claim_request(self, uid, request_id):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
            raise ValueError('操作编号无效')
        try:
            with self.connect() as db:
                db.execute('INSERT INTO requests VALUES(?,?,?)', (uid, request_id, time.time()))
        except sqlite3.IntegrityError:
            raise ValueError('这次操作已受理，请核实原任务或订单，不要重复提交') from None

    @contextmanager
    def school_binding(self, uid, identity):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT school FROM users WHERE id=?', (uid,)).fetchone()
            if not row:
                raise ValueError('网站账号不存在')
            if row['school'] and row['school'] != identity:
                raise ValueError('网站账号已绑定另一学校账号，请使用对应的网站账号登录')
            try:
                db.execute('UPDATE users SET school=? WHERE id=?', (identity, uid))
            except sqlite3.IntegrityError:
                raise ValueError('该学校账号已绑定其他网站账号，请登录原网站账号') from None
            yield

    def ids(self):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT id FROM users')]
