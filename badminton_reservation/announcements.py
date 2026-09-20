"""Site announcements with explicit operator-assigned administrators."""
import argparse
import secrets
import time
from pathlib import Path
from .web_accounts import Accounts


class Announcements:
    def __init__(self, accounts):
        self.accounts = accounts
        with accounts.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS announcement_admins (user_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS announcements (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
                    pinned INTEGER NOT NULL, active INTEGER NOT NULL,
                    version INTEGER NOT NULL, author TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
            ''')

    def grant(self, username):
        with self.accounts.connect() as db:
            row = db.execute('SELECT id FROM users WHERE name=?', (username.lower(),)).fetchone()
            if not row: raise ValueError('该网站用户名尚未注册')
            db.execute('INSERT OR IGNORE INTO announcement_admins VALUES (?)', (row['id'],))

    def can_manage(self, uid):
        with self.accounts.connect() as db:
            return db.execute('SELECT 1 FROM announcement_admins WHERE user_id=?', (uid,)).fetchone() is not None

    def snapshot(self, uid):
        admin = self.can_manage(uid)
        with self.accounts.connect() as db:
            rows = db.execute('SELECT * FROM announcements '+('' if admin else 'WHERE active=1 ')+
                              'ORDER BY pinned DESC,updated DESC LIMIT 100').fetchall()
        values=[]
        for row in rows:
            value={k:row[k] for k in ('id','title','body','pinned','updated')}
            if admin: value.update(active=bool(row['active']),version=row['version'])
            values.append(value)
        return {'canManage':admin,'items':values}

    def save(self, uid, value):
        title, body = value.get('title'), value.get('body')
        if not isinstance(title,str) or not 1 <= len(title.strip()) <= 80: raise ValueError('标题须为 1–80 字')
        if not isinstance(body,str) or not 1 <= len(body.strip()) <= 4000: raise ValueError('正文须为 1–4000 字')
        if type(value.get('active')) is not bool or type(value.get('pinned')) is not bool: raise ValueError('公告状态无效')
        now=time.time()
        with self.accounts.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM announcement_admins WHERE user_id=?',(uid,)).fetchone():
                raise PermissionError('仅公告管理员可操作')
            oid=value.get('id')
            if oid is None:
                oid=secrets.token_hex(12)
                db.execute('INSERT INTO announcements VALUES (?,?,?,?,?,?,?,?,?)',
                    (oid,title.strip(),body.strip(),value['pinned'],value['active'],1,uid,now,now))
            else:
                if not isinstance(oid,str) or type(value.get('version')) is not int: raise ValueError('公告引用无效')
                if db.execute('UPDATE announcements SET title=?,body=?,pinned=?,active=?,version=version+1,author=?,updated=? WHERE id=? AND version=?',
                    (title.strip(),body.strip(),value['pinned'],value['active'],uid,now,oid,value['version'])).rowcount != 1:
                    raise ValueError('公告已被修改或不存在，请刷新后重试')
        return oid


def main():
    parser=argparse.ArgumentParser(description='服务器管理员：授权网站用户管理公告')
    parser.add_argument('--data',required=True,help='服务器数据目录，例如 /data')
    parser.add_argument('--username',required=True,help='已经注册的网站用户名')
    args=parser.parse_args()
    database=Path(args.data).resolve()/'accounts.sqlite3'
    if not database.is_file(): parser.error('数据目录不存在，未创建新数据库')
    try: Announcements(Accounts(database)).grant(args.username)
    except ValueError as exc: parser.error(str(exc))
    print('公告管理权限已授予指定网站账号。')


if __name__=='__main__':main()
