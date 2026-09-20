"""One-shot campus-card payment using the observed first-party payment contract."""
import hashlib
import json
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .ecn_client import ORIGIN
from .resm_api import ResourceAPI, encode_business
from .response import decode_result
from .session import expected_identity

from .runtime import data_root
ROOT = data_root(__file__)
DETAIL_PATH = '/hzsun-resm/chargeManageUseFee/selectChargeManageUseFeeInfoIdAndUserId'
PAY_PATH = '/hzsun-resm/pay/createOrder'


def resolve_order(credentials, submission, *, state_dir=None):
    """Resolve the order for exactly the newly created reservation; no mutation requests."""
    if submission.get('outcome') != 'success':
        raise ValueError('预约尚未确认创建，不能衔接支付')
    reference = submission.get('reservation', {})
    requested = submission.get('requestedResource', {})
    username, user_id = expected_identity(credentials)
    if str(reference.get('code')) != '2':
        raise ValueError('预约返回未明确要求立即支付，停止自动支付')
    if not isinstance(reference.get('occupyId'), str) or not reference['occupyId'].strip():
        raise ValueError('预约返回缺少 occupyId；请核实原预约，不重新预约')
    if not requested.get('infoId') or str(requested.get('userId')) != user_id:
        raise ValueError('预约记录与当前身份不一致')
    for key in ('infoId', 'userId'):
        if key in reference and str(reference[key]) != str(requested[key]):
            raise ValueError('预约返回的资源或身份与请求不一致')
    client = ResourceAPI(credentials)
    try:
        details = client.query(DETAIL_PATH, {'infoId': requested['infoId'],
                              'occupyId': reference['occupyId'], 'userId': user_id})
    finally:
        client.close()
    if not isinstance(details, dict) or not isinstance(details.get('feeOrderId'), str) or not details['feeOrderId']:
        raise ValueError('尚未取得缴费订单号，请查询原预约，不重新预约')
    if str(details.get('userName')) != username:
        raise ValueError('缴费订单不属于当前登录账号')
    for key, value in (('infoId', requested['infoId']), ('occupyId', reference['occupyId'])):
        if key in details and details[key] != value:
            raise ValueError('收费详情与预约不匹配')
    preview = submission['preview']
    if details.get('recordTimeStart') != preview['start'] or details.get('recordTimeEnd') != preview['end']:
        raise ValueError('收费订单时间与预约不匹配')
    try:
        amount = Decimal(str(details['feeOrderAmount']))
        if not amount.is_finite() or amount <= 0: raise ValueError('无有效待支付金额')
    except (KeyError, InvalidOperation):
        raise ValueError('收费金额格式错误') from None
    config = {'infoId': requested['infoId'], 'occupyId': reference['occupyId'],
              'feeOrderId': details['feeOrderId'], 'expectedAmount': str(amount),
              'start': preview['start'], 'end': preview['end']}
    directory = Path(state_dir) if state_dir is not None else ROOT / 'state/orders'
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((username + '|' + reference['occupyId']).encode()).hexdigest()
    destination = directory / (key + '.json')
    temporary = directory / (key + '-' + str(time.time_ns()) + '.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)
    return {'configuration': config, 'orderConfigFile': str(destination.resolve()),
            'feePayStatus': details.get('feePayStatus'), 'feeOrderStatus': details.get('feeOrderStatus'),
            'expiresAt': details.get('feeOrderExpiredDate')}


def prepare(client, credentials, config):
    for key in ('infoId', 'occupyId', 'feeOrderId', 'expectedAmount', 'start', 'end'):
        if config.get(key) in (None, ''): raise ValueError('支付配置缺少字段：' + key)
    username, user_id = expected_identity(credentials)
    details = client.query(DETAIL_PATH, {'infoId': config['infoId'], 'occupyId': config['occupyId'], 'userId': user_id})
    if not isinstance(details, dict) or details.get('feeOrderId') != config['feeOrderId']:
        raise ValueError('缴费订单不匹配，停止支付')
    if str(details.get('userName')) != username:
        raise ValueError('缴费订单不属于当前登录账号，停止支付')
    if details.get('recordTimeStart') != config['start'] or details.get('recordTimeEnd') != config['end']:
        raise ValueError('订单预约时间与配置不一致，停止支付')
    try:
        amount, expected = Decimal(str(details['feeOrderAmount'])), Decimal(str(config['expectedAmount']))
        if not amount.is_finite() or not expected.is_finite() or amount <= 0 or amount != expected:
            raise ValueError('订单金额与预期不一致，停止支付')
    except (KeyError, InvalidOperation):
        raise ValueError('订单金额格式错误') from None
    if str(details.get('feePayStatus')) != '0':
        raise ValueError('该订单不是已确认的未支付状态，不重复支付')
    if str(details.get('feeOrderStatus')) != '0':
        raise ValueError('订单不处于已验证的可支付状态，可能已超时或取消；不重新发起支付')
    if '7' not in str(details.get('chargeMode', '')).split(','):
        raise ValueError('该订单不支持校园卡支付')
    payload = {'feeOrderId': details['feeOrderId'], 'payMode': '7',
               'productName': details['infoName'], 'tranType': details['typeName'],
               'userNo': username, 'equipmentType': 'pc', 'infoId': config['infoId'], 'userId': user_id}
    preview = {'feeOrderId': details['feeOrderId'], 'venue': details['infoName'],
               'start': config['start'], 'end': config['end'], 'amount': str(amount), 'method': '校园卡',
               'feePayStatus': details['feePayStatus'], 'feeOrderStatus': details.get('feeOrderStatus'),
               'expiresAt': details.get('feeOrderExpiredDate')}
    return payload, preview


def pay(credentials, config, *, submit=False, state_dir=None):
    client = ResourceAPI(credentials)
    lock = None
    try:
        payload, preview = prepare(client, credentials, config)
        report = {'preview': preview, 'transport': 'Python requests', 'paymentAttempts': 0,
                  'outcome': 'not_submitted', 'paymentCompleted': False}
        if not submit: return report
        directory = Path(state_dir) if state_dir is not None else ROOT / 'state/payments'
        directory.mkdir(parents=True, exist_ok=True)
        fingerprint = hashlib.sha256((payload['userNo'] + '|' + payload['feeOrderId']).encode()).hexdigest()
        lock_path = directory / (fingerprint + '.lock')
        try: lock = lock_path.open('x', encoding='utf-8')
        except FileExistsError: raise ValueError('该支付已有进行中或待核实任务，停止重复请求') from None
        for item in directory.glob(fingerprint + '-*.json'):
            if json.loads(item.read_text(encoding='utf-8')).get('outcome') in ('pending', 'unknown', 'accepted', 'paid'):
                raise ValueError('同一订单已有成功受理或结果未知的支付，请先核实')
        if client.generator is None: client.bootstrap()
        parameter = client.generator.generate(PAY_PATH, flags=33555232)
        body = encode_business(payload).encode('utf-8')
        record = directory / (fingerprint + '-' + str(time.time_ns()) + '.json')
        report.update(outcome='pending')
        with record.open('x', encoding='utf-8') as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
        report.update(outcome='unknown', paymentAttempts=1, paymentCompleted=None)
        try:
            response = client.session.post(ORIGIN + PAY_PATH, params={client.parameter_name: parameter}, data=body,
                headers={'X-Access-Token': client.credentials['token'], 'Content-Type': 'application/json;charset=UTF-8',
                         'Accept': 'application/json, text/plain, */*', 'Origin': ORIGIN, 'Referer': ORIGIN + '/'},
                timeout=30, allow_redirects=False)
            result = decode_result(response.text)
            code = str(result.get('errCode')) if isinstance(result, dict) and result.get('errCode') is not None else None
            message = str(result.get('customMess') or result.get('message') or '') if isinstance(result, dict) else ''
            message = message.replace(client.credentials['token'], '[REDACTED]')
            report.update(httpStatus=response.status_code, businessCode=code, message=message)
            if response.status_code == 200 and code == '0000':
                report.update(outcome='accepted', paymentCompleted=None,
                              note='支付接口已受理，需核对最终缴费状态；不自动跟随跳转或重复支付')
            elif response.status_code == 200 and code is not None and code != '0000':
                outcome = ('insufficient_balance' if '余额不足' in message else
                           'expired_or_cancelled' if '超时或已取消' in message else 'rejected')
                report.update(outcome=outcome, paymentCompleted=False)
        except Exception as exc:
            report.update(errorType=type(exc).__name__, message='支付结果未知，不自动重试；请核实订单和校园卡流水')
        record.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report
    finally:
        client.close()
        if lock is not None:
            lock.close()
            lock_path.unlink()
