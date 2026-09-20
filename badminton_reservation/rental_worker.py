"""Owner-process-only execution. No caller supplied identity or payment payload."""
from decimal import Decimal
import hashlib
import json
from . import gui_server as gui
from .web_rentals import money, booking_config


def identity(store, owner, credentials):
    username, _ = gui.expected_identity(credentials)
    with store.accounts.connect() as db:
        row = db.execute('SELECT school FROM users WHERE id=?', (owner,)).fetchone()
    if not row or row['school'] != hashlib.sha256(username.encode()).hexdigest():
        raise ValueError('当前学校账号与授权账号不匹配')


def ready(store, owner, app):
    gui.require_phone()
    credentials, status = gui.authenticate()
    identity(store, owner, credentials)
    app.scheduler.note_health(status)
    return credentials


def slots(store, owner, app, oid, config):
    offer = store.live_offer(oid)
    if offer['owner'] != owner or config['venue'] not in json.loads(offer['courts']):
        raise ValueError('无有效场地授权')
    # Validate input before touching the school site. Only a date and venue are used.
    config = booking_config(config, check_time=False)
    credentials = ready(store, owner, app)
    row, day, _, _ = gui.resolve(config)
    result = gui.fetch_availability(credentials, [row], day)['courts'][0]
    if result.get('error'): raise ValueError('暂时无法核实时段，请稍后再试')
    # Never forward backend messages/names/capacity/user metadata to the renter.
    return {'slots': [{'start': s['start'], 'end': s['end'], 'available': s['available'] is True}
                      for s in result['slots']]}


def reconcile(store, owner, app, oid):
    row = store.get(oid, owner)
    if row['owner'] != owner or not row['private_order']: return
    # The owner's RPC lock serializes this with an active payment. After a crash,
    # a durable "paying" record is also safe to reconcile using a read-only query.
    credentials = ready(store, owner, app)
    order = json.loads(row['private_order'])
    username, uid = gui.expected_identity(credentials)
    client = gui.ResourceAPI(credentials)
    try:
        info = client.query(gui.DETAIL_PATH, {'infoId': order['infoId'], 'occupyId': order['occupyId'], 'userId': uid})
    finally:
        client.close()
    if not (isinstance(info, dict) and info.get('feeOrderId') == order['feeOrderId']
            and str(info.get('userName')) == username
            and info.get('recordTimeStart') == order['start'] and info.get('recordTimeEnd') == order['end']
            and Decimal(str(info.get('feeOrderAmount'))) == Decimal(order['expectedAmount'])):
        raise ValueError('订单核对未通过')
    if str(info.get('feePayStatus')) == '1': store.change(oid, owner, 'paid')


def execute(store, owner, app, oid):
    row = store.begin(oid, owner)
    if row is None: return
    phase = 'checking'
    try:
        cfg = booking_config(json.loads(row['config']))
        credentials = ready(store, owner, app)
        court, day, start, end = gui.resolve(cfg)
        fresh = gui.fetch_availability(credentials, [court], day)['courts'][0]
        if not any(s['start'] == start and s['end'] == end and s['available'] is True for s in fresh['slots']):
            store.change(oid, owner, 'failed'); return
        # Commit intent before crossing the mutation boundary. No retry on interruption.
        store.change(oid, owner, 'submitting'); phase = 'submitting'
        result = gui.book(cfg, submit=True, pay_after=False, credentials=credentials)
        submission = result.get('submission', {})
        if submission.get('outcome') != 'success':
            store.change(oid, owner, 'failed' if submission.get('outcome') == 'rejected' else 'unknown'); return
        phase = 'booked'
        if str(submission.get('reservation', {}).get('code')) == '1':
            store.change(oid, owner, 'booked'); return
        order = result.get('order', {}).get('configuration')
        if not order:
            store.change(oid, owner, 'unpaid'); return
        amount = money(order['expectedAmount'], positive=True)
        store.change(oid, owner, 'unpaid', amount=amount, order=order)
        if Decimal(amount) > Decimal(row['max_amount']):
            store.change(oid, owner, 'over_limit'); return
        store.change(oid, owner, 'paying'); phase = 'paying'
        payment = gui.pay(credentials, order, submit=True)
        store.change(oid, owner, 'payment_pending' if payment['outcome'] in ('accepted', 'unknown') else 'unpaid')
        phase = 'payment_pending'
        # Read-only final verification: "accepted" alone must never become "paid".
        try: reconcile(store, owner, app, oid)
        except Exception: pass
    except Exception:
        state = {'checking': 'failed', 'submitting': 'unknown', 'booked': 'unpaid',
                 'paying': 'payment_pending', 'payment_pending': 'payment_pending'}[phase]
        store.change(oid, owner, state)
        # No raw exception or school response reaches either public rental view.
