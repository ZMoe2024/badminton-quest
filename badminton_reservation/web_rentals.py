"""Anonymous, per-reservation delegation. Credentials never leave the owner's worker.

The SQLite transaction is the authorization boundary: an immutable order consumes
one authorized use before any school request. A failed/unknown attempt is never
automatically refunded or resubmitted. All browser responses are explicit allowlists.
"""
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import secrets
import time

TZ = dt.timezone(dt.timedelta(hours=8))
MESSAGES = {
    'queued': '已接单，等待后台处理', 'checking': '正在核实时段',
    'submitting': '正在提交一次预约', 'unknown': '预约结果待核实，请勿重复下单',
    'failed': '本次未完成预约，请出借人核实',
    'booked': '已创建预约，学校未要求立即付款',
    'unpaid': '已创建预约，付款未完成，需出借人处理',
    'over_limit': '已创建预约，金额超出授权，未付款',
    'paying': '正在提交一次支付', 'payment_pending': '支付结果待核实，请勿重复付款',
    'paid': '学校已确认支付成功', 'closed': '学校订单已关闭或过期',
}


def money(value, *, positive=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > 10000 or (positive and number == 0):
            raise ValueError('金额须在 0–10000 元之间，扣款上限必须大于零')
        if number != number.quantize(Decimal('0.01')):
            raise ValueError('金额最多两位小数')
        return format(number, '.2f')
    except (InvalidOperation, TypeError):
        raise ValueError('请输入有效金额') from None


def court_catalog():
    path = Path(__file__).parent / 'state/venues/badminton-courts.json'
    # Use only public venue fields, never cached owner metadata.
    return [{'id': r['infoId'], 'name': r['name']} for r in json.loads(path.read_text(encoding='utf-8'))['courts']]


def booking_config(value, *, check_time=True):
    if not isinstance(value, dict): raise ValueError('请选择场地、日期和时段')
    known = {c['id']: c for c in court_catalog()}
    if not isinstance(value.get('venue'), str) or value['venue'] not in known: raise ValueError('请选择目录中的羽毛球场')
    try:
        day = dt.date.fromisoformat(value['date'])
        start = dt.datetime.strptime(value['start'], '%H:%M').strftime('%H:%M')
        end = dt.datetime.strptime(value['end'], '%H:%M').strftime('%H:%M')
        stamp = dt.datetime.combine(day, dt.time.fromisoformat(start), TZ)
        now = dt.datetime.now(TZ)
        if start >= end or day < now.date() or (check_time and stamp <= now) or day > now.date() + dt.timedelta(days=30): raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError('请选择未来 30 天内同一天的有效时段') from None
    return {'venue': value['venue'], 'date': day.isoformat(), 'start': start, 'end': end}


class Rentals:
    def __init__(self, accounts):
        self.accounts = accounts
        with accounts.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS rental_offers (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, fee TEXT NOT NULL,
                    max_amount TEXT NOT NULL, remaining INTEGER NOT NULL,
                    courts TEXT NOT NULL, expires REAL NOT NULL, active INTEGER NOT NULL,
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS rental_owner ON rental_offers(owner);
                CREATE TABLE IF NOT EXISTS rental_orders (
                    id TEXT PRIMARY KEY, offer TEXT NOT NULL, owner TEXT NOT NULL,
                    renter TEXT NOT NULL, request_id TEXT NOT NULL, config TEXT NOT NULL,
                    fee TEXT NOT NULL, max_amount TEXT NOT NULL, state TEXT NOT NULL,
                    amount TEXT, private_order TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(renter, request_id));
                CREATE INDEX IF NOT EXISTS rental_parties ON rental_orders(owner, renter);
            ''')

    def publish(self, uid, data):
        if data.get('authorized') is not True:
            raise ValueError('请明确授权按次预约及校园卡扣款')
        fee, cap = money(data.get('fee')), money(data.get('maxAmount'), positive=True)
        count, hours = data.get('uses'), data.get('hours')
        if type(count) is not int or not 1 <= count <= 20: raise ValueError('授权次数须为 1–20 次')
        if type(hours) is not int or not 1 <= hours <= 168: raise ValueError('有效期须为 1–168 小时')
        courts = data.get('courts')
        known = {c['id'] for c in court_catalog()}
        if not isinstance(courts, list) or not courts or any(not isinstance(c, str) or c not in known for c in courts):
            raise ValueError('请选择允许使用的羽毛球场地')
        now, oid = time.time(), secrets.token_hex(12)
        with self.accounts.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = db.execute('SELECT school FROM users WHERE id=?', (uid,)).fetchone()
            if not owner or not owner['school']: raise ValueError('请先验证并绑定自己的学校账号')
            if db.execute('SELECT count(*) FROM rental_offers WHERE owner=? AND active=1 AND expires>? AND remaining>0', (uid, now)).fetchone()[0] >= 5:
                raise ValueError('最多同时发布五份授权，请先下架旧授权')
            db.execute('INSERT INTO rental_offers VALUES (?,?,?,?,?,?,?,?,?)',
                       (oid, uid, fee, cap, count, json.dumps(sorted(set(courts))), now+hours*3600, 1, now))
        return oid

    def revoke(self, uid, oid):
        with self.accounts.connect() as db:
            if db.execute('UPDATE rental_offers SET active=0 WHERE id=? AND owner=?', (oid, uid)).rowcount != 1:
                raise ValueError('找不到这份授权')

    def _offer(self, row, own=False):
        value = {'id': row['id'], 'label': '匿名训练家 ' + row['id'][:6].upper(),
                 'fee': row['fee'], 'courts': json.loads(row['courts']),
                 'expires': row['expires'], 'available': bool(row['active'] and row['remaining'] > 0 and row['expires'] > time.time())}
        if own: value.update(maxAmount=row['max_amount'], remaining=row['remaining'])
        return value

    def _order(self, row, uid):
        state = row['state']
        message = MESSAGES[state]
        if state in ('checking', 'submitting', 'paying') and time.time()-row['updated'] > 300:
            message = '处理结果待核实；不会自动重新预约或扣款'
        value = {'id': row['id'], 'label': '匿名训练家 ' + row['offer'][:6].upper(),
                 'config': json.loads(row['config']), 'fee': row['fee'], 'amount': row['amount'],
                 'state': state, 'message': message, 'created': row['created'],
                 'role': 'owner' if row['owner'] == uid else 'renter',
                 'canCheck': bool(row['private_order'])}
        if row['owner'] == uid: value['maxAmount'] = row['max_amount']
        return value

    def snapshot(self, uid):
        with self.accounts.connect() as db:
            offers = db.execute('SELECT * FROM rental_offers WHERE owner!=? AND active=1 AND remaining>0 AND expires>? ORDER BY created DESC LIMIT 100', (uid, time.time())).fetchall()
            mine = db.execute('SELECT * FROM rental_offers WHERE owner=? ORDER BY created DESC LIMIT 100', (uid,)).fetchall()
            orders = db.execute('SELECT * FROM rental_orders WHERE owner=? OR renter=? ORDER BY created DESC LIMIT 100', (uid, uid)).fetchall()
        return {'offers': [self._offer(r) for r in offers], 'mine': [self._offer(r, True) for r in mine],
                'orders': [self._order(r, uid) for r in orders], 'courts': court_catalog()}

    def live_offer(self, oid):
        with self.accounts.connect() as db:
            row = db.execute('SELECT * FROM rental_offers WHERE id=? AND active=1 AND remaining>0 AND expires>?', (oid, time.time())).fetchone()
        if not row: raise ValueError('这份授权已下架、到期或次数已用完')
        return dict(row)

    def request(self, uid, data):
        if data.get('confirmed') is not True: raise ValueError('请确认场地、时段及展示的服务费')
        config = booking_config(data.get('config'))
        request_id = data.get('requestId')
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100: raise ValueError('请求编号无效')
        oid, now = secrets.token_hex(12), time.time()
        with self.accounts.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM rental_orders WHERE renter=? AND request_id=?', (uid, request_id)).fetchone()
            if prior: return prior['id']  # Return original; never consume twice, even after restart.
            offer = db.execute('SELECT * FROM rental_offers WHERE id=? AND active=1 AND remaining>0 AND expires>?', (data.get('offerId'), now)).fetchone()
            if not offer or offer['owner'] == uid: raise ValueError('请选择其他训练家的有效授权')
            if config['venue'] not in json.loads(offer['courts']): raise ValueError('此场地不在出借人的授权范围')
            if money(data.get('fee')) != offer['fee']: raise ValueError('服务费已变化，请重新核对')
            encoded = json.dumps(config, sort_keys=True)
            # Different request IDs / different lenders must not create duplicate reservations.
            if db.execute("SELECT 1 FROM rental_orders WHERE (renter=? OR owner=?) AND config=? AND state NOT IN ('failed','closed')", (uid, offer['owner'], encoded)).fetchone():
                raise ValueError('此场地时段已有接单或待核实记录，请先查看原订单')
            db.execute('UPDATE rental_offers SET remaining=remaining-1 WHERE id=?', (offer['id'],))
            db.execute('INSERT INTO rental_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (oid, offer['id'], offer['owner'], uid, request_id, encoded, offer['fee'], offer['max_amount'], 'queued', None, None, now, now))
        return oid

    def get(self, oid, uid):
        with self.accounts.connect() as db:
            row = db.execute('SELECT * FROM rental_orders WHERE id=? AND (owner=? OR renter=?)', (oid, uid, uid)).fetchone()
        if not row: raise ValueError('找不到这笔订单')
        return dict(row)  # INTERNAL only; browser endpoints must use public_order.

    def public_order(self, oid, uid):
        return self._order(self.get(oid, uid), uid)

    def begin(self, oid, owner):
        with self.accounts.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM rental_orders WHERE id=? AND owner=?', (oid, owner)).fetchone()
            if not row or row['state'] != 'queued': return None
            db.execute("UPDATE rental_orders SET state='checking', updated=? WHERE id=?", (time.time(), oid))
        return dict(row)

    def change(self, oid, owner, state, *, amount=None, order=None):
        if state not in MESSAGES: raise ValueError('无效状态')
        with self.accounts.connect() as db:
            db.execute('UPDATE rental_orders SET state=?, updated=?, amount=COALESCE(?,amount), private_order=COALESCE(?,private_order) WHERE id=? AND owner=?',
                       (state, time.time(), amount, json.dumps(order) if order else None, oid, owner))
