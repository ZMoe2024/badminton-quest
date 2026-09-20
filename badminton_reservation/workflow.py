"""Shared session preparation and reservation workflow for CLI and Python callers."""
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .badminton_booking import execute, resolve
from .session import ensure_session
from . import session_store
from .venue_catalog import read_credentials
from .payment import resolve_order, pay

ROOT = Path(__file__).resolve().parent
DEFAULT_SESSION = ROOT / ('config/session.keychain' if sys.platform == 'darwin' else 'config/session.dpapi')
DEFAULT_CONFIG = ROOT / 'config/booking.json'


def authenticate(*, credentials=None, credentials_file=None, session_file=None,
                 force_renew=False, import_session=False):
    if credentials is not None and credentials_file is not None:
        raise ValueError('只能提供一份凭据输入')
    destination = Path(session_file) if session_file is not None else None
    if import_session:
        inputs = credentials if credentials is not None else read_credentials(credentials_file or '-')
        destination = destination or DEFAULT_SESSION
    elif credentials is not None:
        inputs = credentials
    elif credentials_file is not None:
        inputs = read_credentials(credentials_file)
    elif destination is not None or DEFAULT_SESSION.exists():
        destination = destination or DEFAULT_SESSION
        inputs = session_store.load(destination)
    else:
        raise ValueError('尚未登录，请到登录设置点击「登录学校账号」；命令行也可用 auth-import 导入会话。')
    inputs, status = ensure_session(inputs, force_renew=force_renew)
    if destination is not None:
        session_store.save(destination, inputs)
    status = dict(status, sessionStored=destination is not None)
    return inputs, status


def book(config=None, *, submit=False, credentials=None, credentials_file=None, session_file=None,
         pay_after=False, expected_amount=None):
    """Validate or submit with automatic authentication; never retries a booking POST."""
    if config is None:
        config = DEFAULT_CONFIG
    if isinstance(config, (str, Path)):
        config = json.loads(Path(config).read_text(encoding='utf-8-sig'))
    resolve(config)
    if pay_after:
        if not submit: raise ValueError('支付衔接只能用于正式提交')
    amount = None
    if pay_after and expected_amount is not None:
        try:
            amount = Decimal(str(expected_amount))
            if not amount.is_finite() or amount <= 0: raise ValueError('预期支付金额必须大于零')
        except InvalidOperation:
            raise ValueError('衔接支付须提供有效的 expected_amount / --expected-amount') from None
    inputs, status = authenticate(credentials=credentials, credentials_file=credentials_file, session_file=session_file)
    result = execute(inputs, config, submit=submit)
    result['authentication'] = status
    submission = result.get('submission', {})
    if submit and submission.get('outcome') == 'success':
        code = str(submission.get('reservation', {}).get('code'))
        if code == '1':
            submission['paymentStatus'] = 'not_requested_by_server'
        else:
            try:
                result['order'] = resolve_order(inputs, submission)
                submission['paymentStatus'] = 'order_resolved'
                if pay_after:
                    order_config = dict(result['order']['configuration'])
                    if amount is not None:
                        order_config['expectedAmount'] = str(amount)
                    result['order']['amountPolicy'] = 'exact' if amount is not None else 'server_order_amount'
                    result['payment'] = pay(inputs, order_config, submit=True)
                    submission['paymentStatus'] = result['payment']['outcome']
            except Exception as exc:
                result['errors'] = [{'phase': 'payment' if 'order' in result else 'order_lookup',
                    'errorType': type(exc).__name__,
                    'message': str(exc) if isinstance(exc, ValueError) else '衔接失败；请查询原预约，不重新提交预约'}]
                submission['paymentStatus'] = 'handoff_failed'
    return result
