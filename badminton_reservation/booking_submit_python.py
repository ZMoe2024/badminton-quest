"""Pure requests booking check/submission with freshly supplied login credentials."""
import argparse
import base64
import hashlib
import json
import sys
import time
import secrets
from pathlib import Path
from urllib.parse import urlencode
from .ecn_client import BootstrapClient, decode_response
from .response import decode_result
from .runtime import data_root


def run(inputs, submit=False, booking_data=None):
    client = BootstrapClient(inputs)
    try:
        token = client.credentials['token']
        part = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        user = json.loads(base64.b64decode(inputs['currentUser']).decode('utf-8'))
        token_expired_by_claim = claims.get('exp', 0) <= time.time()
        if str(user.get('username')) != str(claims.get('username')) or not user.get('userId'):
            raise ValueError('当前页面用户与登录令牌不一致')
        booking = (json.loads((data_root(__file__) / 'config/booking_data.json').read_text(encoding='utf-8'))
                   if booking_data is None else json.loads(json.dumps(booking_data)))
        booking.update(jobNum=str(user['username']), userId=str(user['userId']))
        booking['users'] = [{'jobNum': booking['jobNum'], 'userId': booking['userId'], 'contact': '', 'checked': False}]
        if not submit:
            response = client.get()
            result = decode_result(response.text)
            return {'phase': 'probe', 'httpStatus': response.status_code, 'tokenExpiredByClaim': token_expired_by_claim,
                    'businessCode': result.get('errCode') if isinstance(result, dict) else None}
        fingerprint = hashlib.sha256('|'.join(str(booking[k]) for k in
            ['jobNum', 'userId', 'infoId', 'occupyTimeStart', 'occupyTimeEnd']).encode()).hexdigest()
        folder = (data_root(__file__) / 'state/attempts'); folder.mkdir(parents=True, exist_ok=True)
        for previous in folder.glob(fingerprint + '-*.json'):
            prior = json.loads(previous.read_text(encoding='utf-8'))
            if prior.get('outcome') in ['pending', 'unknown', 'success']:
                raise ValueError('同一笔已有成功或结果不明的提交；请先核实，不自动重复提交')
        client.bootstrap()
        chars = 'abcdefhijkABCDEFGHJKMNPQRSTWXYZmnprstwxyz12345678'
        body = ''.join(secrets.choice(chars) for _ in range(13))
        body += base64.b64encode(json.dumps(booking, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).decode('ascii')
        body += ''.join(secrets.choice(chars) for _ in range(6))
        path = '/hzsun-resm/sub/occupy/doOccupy'
        parameter = client.generator.generate(path, flags=33555232)
        preview = {'account': booking['jobNum'][:2] + '****' + booking['jobNum'][-2:],
                   'location': booking['location'], 'start': booking['occupyTimeStart'], 'end': booking['occupyTimeEnd']}
        record = folder / (fingerprint + '-' + str(time.time_ns()) + '.json')
        with record.open('x', encoding='utf-8') as file:
            json.dump({'outcome': 'pending', 'preview': preview}, file, ensure_ascii=False)
        report = {'outcome': 'unknown', 'preview': preview, 'transport': 'Python requests', 'postAttempts': 1,
                  'tokenExpiredByClaim': token_expired_by_claim}
        try:
            response = client.session.post('https://resm.lzjtu.edu.cn' + path,
                params={client.parameter_name: parameter}, data=body.encode('utf-8'),
                headers={'Content-Type': 'application/json;charset=UTF-8', 'X-Access-Token': token,
                         'Referer': 'https://resm.lzjtu.edu.cn/', 'Origin': 'https://resm.lzjtu.edu.cn',
                         'Accept': 'application/json, text/plain, */*'}, timeout=30, allow_redirects=False)
            result = decode_result(response.text)
            code = result.get('errCode') if isinstance(result, dict) else None
            message = str(result.get('customMess') or result.get('errMsg') or result.get('msg') or result.get('message') or '') if isinstance(result, dict) else ''
            report.update(httpStatus=response.status_code, businessCode=code,
                          outcome='success' if response.status_code == 200 and str(code) == '0000' else ('rejected' if code is not None else 'unknown'),
                          message=message.replace(token, '[REDACTED]'), responseBytes=len(response.content),
                          challenge='$_ts.cd' in response.text)
            if report['outcome'] == 'success':
                report.update(bookingCreated=True, paymentStatus='not_checked',
                              note='预约申请创建成功；不代表已完成缴费，需查询对应订单')
                details = result.get('responseResult')
                if isinstance(details, dict):
                    report['reservation'] = {key: details[key] for key in
                                             ('occupyId', 'infoId', 'userId', 'code') if key in details}
                report['requestedResource'] = {'infoId': booking['infoId'], 'userId': booking['userId']}
        except Exception as exc:
            report.update(errorType=type(exc).__name__, message='提交结果未知，不会自动重试')
        record.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        report['recordFile'] = str(record.resolve())
        return report
    finally:
        client.close()


if __name__ == '__main__':
    from .compat import booking_main
    raise SystemExit(booking_main())
