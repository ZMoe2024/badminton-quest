"""Business request encoding layered over the independently generated URL parameter."""
import base64
import json
import secrets
import time
from urllib.parse import urlencode
from .ecn_client import BootstrapClient, ORIGIN
from .response import decode_result

CHARS = 'abcdefhijkABCDEFGHJKMNPQRSTWXYZmnprstwxyz12345678'


def encode_business(value):
    if not isinstance(value, str):
        if value is None: value = 'null'
        elif isinstance(value, bool): value = 'true' if value else 'false'
        elif isinstance(value, (dict, list)): value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        else: value = str(value)
    if value == '':
        return ''
    return (''.join(secrets.choice(CHARS) for _ in range(13)) +
            base64.b64encode(value.encode('utf-8')).decode('ascii') +
            ''.join(secrets.choice(CHARS) for _ in range(6)))


class ResourceAPI(BootstrapClient):
    def query(self, path, params=None):
        values = dict(params or {})
        values['t'] = int(time.time() * 1000)
        query = urlencode({k: encode_business(v) for k, v in values.items()})
        return self.unpack(self.get(path + '?' + query))

    def post_query(self, path, data):
        allowed = {'/hzsun-resm/resmanageinfo/queryList', '/hzsun-resm/resourcetree/queryResourceTree',
                   '/hzsun-resm/resourceTypeStatus/queryResStatusForPlan',
                   '/hzsun-resm/sub/occupy/queryTimetableEmploy',
                   '/hzsun-resm/resourceTypeStatus/queryInfoOccCount'}
        if path not in allowed:
            raise ValueError('该入口只允许已确认的资源查询接口')
        if self.generator is None: self.bootstrap()
        parameter = self.generator.generate(path, flags=33555232)
        response = self.session.post(ORIGIN + path, params={self.parameter_name: parameter},
            data=encode_business(data).encode('utf-8'),
            headers={'X-Access-Token': self.credentials['token'], 'Content-Type': 'application/json;charset=UTF-8',
                     'Accept': 'application/json, text/plain, */*', 'Referer': ORIGIN + '/', 'Origin': ORIGIN},
            timeout=30, allow_redirects=False)
        self.note_response(response)
        return self.unpack(response)

    @staticmethod
    def unpack(response):
        result = decode_result(response.text)
        if not isinstance(result, dict) or str(result.get('errCode')) != '0000':
            code = result.get('errCode') if isinstance(result, dict) else None
            message = str(result.get('customMess') or result.get('errMsg') or result.get('msg') or result.get('message') or '') if isinstance(result, dict) else ''
            raise ValueError(f'资源查询失败：HTTP {response.status_code}，业务码 {code}，{message}')
        return result.get('responseResult')
