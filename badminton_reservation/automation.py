"""Durable local reservation tasks. Only read operations may be retried blindly."""
import copy
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid
from decimal import Decimal, InvalidOperation

from .availability import fetch_availability, now_local, timestamp
from .badminton_booking import resolve
from .workflow import authenticate, book
from .session import expected_identity, LoginRequired
from .payment import pay, DETAIL_PATH
from .resm_api import ResourceAPI

ROOT = Path(__file__).resolve().parent
ACTIVE = {'waiting', 'checking', 'submitting', 'paying', 'unknown', 'payment_pending'}
BLOCKING = ACTIVE | {'needs_login', 'paused', 'attention', 'booked', 'paid'}


class StateWriteError(RuntimeError):
    pass


def stamp(value=None):
    return (value or now_local()).isoformat(timespec='seconds')


def local_time(value):
    result = dt.datetime.fromisoformat(str(value))
    if result.tzinfo is not None:
        result = result.astimezone(dt.timezone(dt.timedelta(hours=8))).replace(tzinfo=None)
    return result


def account_key(credentials):
    return hashlib.sha256('|'.join(expected_identity(credentials)).encode()).hexdigest()


def normalize(data):
    mode = data.get('mode')
    if mode not in ('scheduled', 'watch', 'scheduled_watch'):
        raise ValueError('请选择定时预约、立即候补或定时＋候补')
    candidates = data.get('candidates')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 6:
        raise ValueError('请选择1至6个候选场地')
    resolved = []
    for venue in candidates:
        row, date, start, end = resolve(dict(venue=venue, date=data['date'], start=data['start'], end=data['end']))
        if row['infoId'] in [r['infoId'] for r in resolved]: raise ValueError('候选场地不能重复')
        resolved.append({'infoId': row['infoId'], 'name': row['name']})
    run_at = local_time(data['runAt']) if mode != 'watch' else now_local()
    until = local_time(data['until'])
    playing = local_time(date + 'T' + start)
    if until <= now_local() or until <= run_at or until > playing:
        raise ValueError('截止时间须晚于现在及开始执行时间，且不晚于打球开始时间')
    if mode != 'watch' and run_at < now_local() - dt.timedelta(seconds=30):
        raise ValueError('定时开始时间已经过去，请重新选择或使用立即候补')
    interval = data.get('interval', 30)
    if isinstance(interval, bool) or not isinstance(interval, int) or not 30 <= interval <= 600:
        raise ValueError('候补查询间隔须为30至600秒')
    enabled_pay = data.get('pay') is True
    amount = None
    if enabled_pay:
        try:
            amount = Decimal(str(data.get('maxAmount')))
            if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
                raise ValueError('支付上限须为正数，最多两位小数')
        except InvalidOperation:
            raise ValueError('请填写有效的支付金额上限') from None
    return dict(mode=mode, candidates=resolved, date=date, start=start, end=end,
                runAt=stamp(run_at), until=stamp(until), interval=interval,
                pay=enabled_pay, maxAmount=str(amount) if amount is not None else None)


class Scheduler:
    def __init__(self, network_lock, path=None):
        self.path = Path(path) if path else ROOT / 'state/automation/tasks.json'
        self.network_lock = network_lock
        self.guard = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.jobs = {}
        self.fatal = None
        self.health = {'state': 'unchecked', 'message': '启用任务后持续维护登录', 'checkedAt': None,
                       'renewedAt': None, 'nextCheckAt': None, 'fullLogin': 'unverified'}
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if data.get('version') != 1 or not isinstance(data.get('jobs'), dict): raise ValueError()
                self.jobs = data['jobs']
                for job in self.jobs.values():
                    if job['state'] == 'checking':
                        job['state'] = 'waiting'
                    elif job['state'] in ('submitting', 'paying'):
                        job['state'] = 'payment_pending' if job['state'] == 'paying' else 'unknown'
                        job['message'] = '上次操作中断，先查询原记录，不重复提交'
                        job['nextCheckAt'] = stamp()
        except Exception:
            self.fatal = '任务文件无法读取，自动执行已停止。请保留原文件并检查，不能覆盖重建。'

    def _save(self):
        if self.fatal: raise ValueError(self.fatal)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('x', encoding='utf-8') as f:
                json.dump({'version': 1, 'jobs': self.jobs}, f, ensure_ascii=False, indent=2)
                f.flush(); os.fsync(f.fileno())
            os.replace(temp, self.path)
        except Exception as exc:
            self.fatal = '任务状态保存失败，已停止自动执行，请检查本机任务文件。'
            raise StateWriteError(self.fatal) from exc

    def _change(self, job, state, message, **changes):
        job.update(state=state, message=message, updatedAt=stamp(), **changes)
        job['events'] = (job.get('events', []) + [{'at': stamp(), 'state': state, 'message': message}])[-60:]
        self._save()

    def snapshot(self):
        with self.guard:
            jobs = sorted(self.jobs.values(), key=lambda x: x['createdAt'], reverse=True)
            return {'jobs': [{k: copy.deepcopy(v) for k, v in j.items() if k != 'accountKey'} for j in jobs],
                    'health': copy.deepcopy(self.health), 'error': self.fatal, 'serverTime': stamp(),
                    'running': bool(self.thread and self.thread.is_alive())}

    def due_soon(self, seconds=45):
        with self.guard:
            now = now_local()
            return any(j['state'] == 'waiting' and local_time(j['config']['until']) > now
                       and local_time(j['nextCheckAt']) <= now + dt.timedelta(
                           seconds=seconds if not j['checks'] and j['config']['mode'] != 'watch' else 2)
                       for j in self.jobs.values())

    def assert_session_compatible(self, credentials):
        identity = account_key(credentials)
        with self.guard:
            if any(j['state'] in ACTIVE | {'needs_login', 'paused'} and
                   j.get('accountKey') not in (None, identity) for j in self.jobs.values()):
                raise ValueError('另一个账号还有未完成的自动任务。请先停止等待任务或核实原订单，再切换账号；原会话保留。')

    def save_draft(self, data, key=None):
        cfg = normalize(data)
        with self.guard:
            if key:
                job = self.jobs.get(key)
                if job is None or job['state'] != 'draft': raise ValueError('仅可修改尚未启用的草稿')
                job['config'] = cfg
            else:
                key = uuid.uuid4().hex
                job = {'id': key, 'config': cfg, 'state': 'draft', 'createdAt': stamp(),
                       'checks': 0, 'failures': 0, 'cancelRequested': False, 'events': []}
                self.jobs[key] = job
            self._change(job, 'draft', '草稿已保存，尚未启用')
            return copy.deepcopy(job)

    def enable(self, key, credentials):
        with self.guard:
            job = self.jobs.get(key)
            if not job or job['state'] not in ('draft', 'needs_login', 'paused') or job.get('submittedAt'):
                raise ValueError('这个任务不能恢复；已有提交的任务须先核实原预约')
            cfg = job['config']
            if local_time(cfg['until']) <= now_local(): raise ValueError('任务已超过截止时间')
            identity = account_key(credentials)
            if job.get('accountKey') not in (None, identity): raise ValueError('当前账号与原任务不一致')
            for other in self.jobs.values():
                if other['id'] == key or other['state'] not in BLOCKING or other.get('accountKey') != identity: continue
                c = other['config']
                if c['date'] == cfg['date'] and c['start'] < cfg['end'] and c['end'] > cfg['start']:
                    raise ValueError('同一账号已有重叠时段任务，请先处理原任务，不能重复启用')
            name, _ = expected_identity(credentials)
            job.update(accountKey=identity, account=name[:2]+'****'+name[-2:], failures=0, cancelRequested=False)
            self._change(job, 'waiting', '任务已启用，等待开始或下一轮查询',
                         nextCheckAt=stamp(max(now_local(), local_time(cfg['runAt']))))
            return {'id': key}

    def cancel(self, key):
        with self.guard:
            job = self.jobs.get(key)
            if not job: raise ValueError('任务不存在')
            if job['state'] in ('submitting', 'paying', 'unknown', 'payment_pending'):
                self._change(job, job['state'], '已请求停止后续操作；已发出的请求仍需核实', cancelRequested=True)
            elif job['state'] in ('draft', 'waiting', 'checking', 'needs_login', 'paused'):
                self._change(job, 'cancelled', '任务已取消', cancelRequested=True)
            return {'id': key, 'state': job['state']}

    def note_health(self, status=None, error=None):
        with self.guard:
            self.health.update(checkedAt=stamp(), nextCheckAt=stamp(now_local()+dt.timedelta(minutes=5)))
            if error:
                self.health.update(state='needs_login' if isinstance(error, LoginRequired) else 'error',
                                   message='学校认证需要重新登录' if isinstance(error, LoginRequired) else '检查暂未通过，将重试')
            else:
                self.health.update(state='valid', message='学校应用会话有效')
                if status and status.get('renewed'):
                    self.health['renewedAt'] = stamp()
                    self.health.pop('renewalWarning', None)

    def _credentials(self, job=None):
        try:
            credentials, status = authenticate()
            # JWT claims are only a renewal hint; the server probe above verifies validity.
            # Failed proactive renewal must not discard a still-valid application session.
            try:
                encoded = credentials.get('token', '').split('.')[1]
                expires = float(json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))['exp'])
                now_epoch = now_local().replace(tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()
                near_expiry = expires <= now_epoch + 300
            except (IndexError, KeyError, ValueError, TypeError): near_expiry = False
            if near_expiry and credentials.get('ssoCookies'):
                try: credentials, status = authenticate(force_renew=True)
                except Exception:
                    with self.guard: self.health['renewalWarning'] = '主动续期暂未完成；当前应用会话仍有效'
            self.note_health(status)
        except Exception as exc:
            self.note_health(error=exc)
            raise
        if job and account_key(credentials) != job['accountKey']:
            raise LoginRequired('当前登录账号与任务绑定账号不同，请恢复原账号')
        return credentials

    def start(self):
        if self.thread: return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lease = self.path.with_suffix('.lock').open('a+b')
        try:
            self.lease.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            self.fatal = '另一个后台已管理这份任务，请使用原界面，不能同时运行两个执行器。'
            return
        if self.fatal:
            self.lease.close()
            return
        self._save()
        self.thread = threading.Thread(target=self._loop, name='badminton-tasks', daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try: self.tick()
            except Exception:
                # A failed durable write must stop the worker, never permit an unrecorded POST.
                with self.guard: self.fatal = '后台状态保存失败，已停止自动执行，请检查本机任务文件。'
            self.stop_event.wait(1)
        self.lease.close()

    def tick(self):
        if self.fatal or not self.network_lock.acquire(blocking=False): return
        try:
            with self.guard:
                now = now_local()
                for j in self.jobs.values():
                    if j['state'] in ('waiting', 'needs_login', 'paused') and local_time(j['config']['until']) <= now:
                        self._change(j, 'expired', '已到截止时间，没有继续预约')
                due = sorted([j for j in self.jobs.values() if j['state'] in ('waiting', 'unknown', 'payment_pending')
                              and local_time(j['nextCheckAt']) <= now], key=lambda j: j['nextCheckAt'])
                job = due[0] if due else None
            if job:
                if job['state'] in ('unknown', 'payment_pending'): self._reconcile(job)
                else: self._run(job)
                return
            with self.guard:
                active = [j for j in self.jobs.values() if j['state'] in ACTIVE | {'needs_login'}]
                next_check = local_time(self.health['nextCheckAt']) if self.health['nextCheckAt'] else now
                preparing = any(0 < (local_time(j['config']['runAt'])-now).total_seconds() <= 60 for j in active)
                recent = self.health['checkedAt'] and (now-local_time(self.health['checkedAt'])).total_seconds() < 30
            if active and (now >= next_check or (preparing and not recent)):
                try: self._credentials()
                except LoginRequired:
                    with self.guard:
                        for j in active:
                            if j['state'] == 'waiting': self._change(j, 'needs_login', '自动续期失败，需恢复登录后手动继续')
                except Exception: pass
        finally: self.network_lock.release()

    def _allowed(self, job):
        if job['cancelRequested'] or job['state'] == 'cancelled': return False
        if local_time(job['config']['until']) <= now_local():
            self._change(job, 'expired', '查询期间已到截止时间，没有提交')
            return False
        return True

    def _run(self, job):
        cfg = job['config']
        try:
            with self.guard:
                if not self._allowed(job): return
                self._change(job, 'checking', '正在查询网站最新时段与占用', checks=job['checks']+1, lastCheckAt=stamp())
            credentials = self._credentials(job)
            cfg = job['config']
            rows = [resolve(dict(venue=r['infoId'], date=cfg['date'], start=cfg['start'], end=cfg['end']))[0]
                    for r in cfg['candidates']]
            result = fetch_availability(credentials, rows, cfg['date'])
            selected, errors = None, []
            for row in result['courts']:
                if row.get('error'): errors.append(row['error']); continue
                slot = next((s for s in row['slots'] if s['start'] == cfg['start'] and s['end'] == cfg['end']), None)
                if slot and slot['available']: selected = row; break
            with self.guard:
                if not self._allowed(job): return
                if selected is None:
                    if errors: raise ValueError('部分场地查询失败，稍后重新核实')
                    if result['courts'] and all(r['slots'] and not any(s['start'] == cfg['start'] and s['end'] == cfg['end'] for s in r['slots']) for r in result['courts']):
                        self._change(job, 'attention', '网站返回的时段与目标不匹配，请核对配置'); return
                    if cfg['mode'] == 'scheduled':
                        self._change(job, 'unavailable', '定时查询完成，没有可预约场地；未启用候补'); return
                    self._change(job, 'waiting', '没有可预约空位，继续候补', failures=0,
                                 nextCheckAt=stamp(now_local()+dt.timedelta(seconds=cfg['interval'])))
                    return
                job['selected'] = selected['infoId']
                self._change(job, 'submitting', '已找到空位，正在提交一次预约', submittedAt=stamp())
            target = dict(venue=selected['infoId'], date=cfg['date'], start=cfg['start'], end=cfg['end'])
            result = book(target, submit=True, credentials=credentials, pay_after=False)
            with self.guard:
                job['result'] = result
                submission = result.get('submission', {})
                outcome = submission.get('outcome')
                if outcome == 'rejected':
                    # No verified machine error code for an occupancy race is known yet.
                    # Never classify quota/identity rejection as a retryable race by a fuzzy string.
                    self._change(job, 'attention', '服务器拒绝：'+str(submission.get('message') or '请核对原预约记录')); return
                if outcome != 'success':
                    self._change(job, 'unknown', '预约结果未知，先查询原记录，不重新提交', nextCheckAt=stamp(now_local()+dt.timedelta(seconds=15)), verifyAttempts=0); return
                self._change(job, 'booked', '预约成功，已停止候补')
                if not cfg['pay'] or job['cancelRequested']: return
                if str(submission.get('reservation', {}).get('code')) == '1':
                    self._change(job, 'booked', '预约成功，服务器未要求立即付款'); return
                order = result.get('order', {}).get('configuration')
                if not order:
                    self._change(job, 'booked', '预约成功；未取得可支付订单，请核实原预约'); return
                amount = Decimal(str(order['expectedAmount']))
                if not amount.is_finite() or amount <= 0 or amount > Decimal(cfg['maxAmount']):
                    self._change(job, 'booked', '预约成功，订单金额超出上限或无效，未付款'); return
                self._change(job, 'paying', '按实际订单金额发起一次校园卡支付')
            payment = pay(credentials, order, submit=True)
            with self.guard:
                job['result']['payment'] = payment
                if payment['outcome'] in ('accepted', 'unknown'):
                    self._change(job, 'payment_pending', '支付需核实最终状态，不重复付款', nextCheckAt=stamp(now_local()+dt.timedelta(seconds=15)), verifyAttempts=0)
                else:
                    self._change(job, 'booked', '预约成功，付款未完成：'+str(payment.get('message') or payment['outcome']))
        except StateWriteError:
            raise
        except Exception as exc:
            with self.guard:
                if job['state'] == 'cancelled': return
                if job['state'] in ('submitting', 'paying'):
                    state = 'unknown' if job['state'] == 'submitting' else 'payment_pending'
                    self._change(job, state, '操作中断，查询原记录，不自动重新提交', nextCheckAt=stamp(now_local()+dt.timedelta(seconds=15)), verifyAttempts=0)
                elif job.get('submittedAt'):
                    self._change(job, 'booked', '已创建预约，后续处理未完成，请核对原订单')
                elif isinstance(exc, LoginRequired):
                    self._change(job, 'needs_login', str(exc))
                else:
                    count = job.get('failures', 0)+1
                    self._change(job, 'paused' if count >= 5 else 'waiting', '查询暂未完成；连续五次失败会暂停', failures=count,
                                 nextCheckAt=stamp(now_local()+dt.timedelta(seconds=min(600, cfg['interval']*2**min(count-1,4)))))

    def _reconcile(self, job):
        try:
            credentials = self._credentials(job)
            client = ResourceAPI(credentials)
            try:
                if job['state'] == 'payment_pending':
                    order = job.get('result', {}).get('order', {}).get('configuration')
                    if not order: raise ValueError('缺少原订单，需人工核实')
                    username, uid = expected_identity(credentials)
                    info = client.query(DETAIL_PATH, {'infoId':order['infoId'], 'occupyId':order['occupyId'], 'userId':uid})
                    if (info.get('feeOrderId') == order['feeOrderId'] and str(info.get('feePayStatus')) == '1'
                        and str(info.get('userName')) == username
                        and Decimal(str(info.get('feeOrderAmount'))) == Decimal(str(order['expectedAmount']))
                        and info.get('recordTimeStart') == order['start'] and info.get('recordTimeEnd') == order['end']):
                        with self.guard: self._change(job, 'paid', '已查询确认订单支付成功')
                        return
                else:
                    c = job['config']
                    records = client.query('/hzsun-resm/subUseRecord/queryReservationRecord', {
                        'limit':100, 'offset':1, 'searchStartTime':c['date']+' 00:00:00',
                        'searchEndTime':c['date']+' 23:59:59', 'recordStatus':'',
                        'orderByField':'recordTimeStart,recordCreateDate,occupyId', 'orderByFlag':'desc'})
                    matches = []
                    for r in records.get('rows', []):
                        if r.get('infoId') != job.get('selected'): continue
                        if r.get('recordTimeStart') != c['date']+' '+c['start']+':00' or r.get('recordTimeEnd') != c['date']+' '+c['end']+':00': continue
                        try: created = timestamp(r['recordCreateDate'])
                        except (KeyError, ValueError, TypeError): continue
                        if created >= local_time(job['submittedAt'])-dt.timedelta(seconds=5):
                            matches.append({k:r.get(k) for k in ('occupyId','recordUseStatus','feePayStatus')})
                    if len(matches) == 1:
                        with self.guard:
                            job['recoveredRecord'] = matches[0]
                            self._change(job, 'attention', '找到匹配预约，请核实状态及原订单；不会自动再预约或付款')
                        return
            finally: client.close()
        except Exception: pass
        with self.guard:
            count = job.get('verifyAttempts', 0)+1
            self._change(job, 'attention' if count >= 3 else job['state'],
                         '尚不能确认最终结果，请核实原预约与订单；不会重发', verifyAttempts=count,
                         nextCheckAt=stamp(now_local()+dt.timedelta(seconds=30)))
