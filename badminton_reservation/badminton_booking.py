"""Resolve a badminton booking configuration, validate live settings, and optionally submit once."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from .badminton import CATALOG
from .booking_submit_python import run
from .resm_api import ResourceAPI
from .venue_catalog import read_credentials, select_resource

from .runtime import data_root
ROOT = data_root(__file__)


def resolve(config):
    row = select_resource(json.loads(CATALOG.read_text(encoding='utf-8'))['courts'], config['venue'])
    date = dt.date.fromisoformat(config['date']).isoformat()
    start = dt.datetime.strptime(config['start'], '%H:%M').strftime('%H:%M')
    end = dt.datetime.strptime(config['end'], '%H:%M').strftime('%H:%M')
    if start >= end:
        raise ValueError('结束时间必须晚于开始时间，当前仅支持当天的完整时段')
    return row, date, start, end


def validate_slot(blocks, info_id, start, end):
    matches = [group for group in blocks if group.get('infoId') == info_id
               and any(b.get('blockStartTime') == start and b.get('blockEndTime') == end
                       for b in group.get('resUseTimeBlockInfoList', []))]
    if len(matches) != 1:
        raise ValueError('所选时间不是该场地当天的单个完整配置时段')
    group = matches[0]
    if not int(group['minBlockNum']) <= 1 <= int(group['maxBlockNum']):
        raise ValueError('该场地当前不允许单时段预约')


def execute(credentials, config, submit=False):
    row, date, start, end = resolve(config)
    client = ResourceAPI(credentials)
    try:
        detail = client.query('/hzsun-resm/resmanageinfo/queryResInfo', {'resId': row['infoId']})
        if detail.get('infoId') != row['infoId'] or str(detail.get('infoStatus')) != '1':
            raise ValueError('场地状态或ID已变化，请刷新目录')
        blocks = client.query('/hzsun-resm/subManageTimeConfig/selectTimeBlock',
                              {'infoId': row['infoId'], 'dateTime': date})
        validate_slot(blocks, row['infoId'], start, end)
        form = client.query('/hzsun-resm/formManageConifg/selectByInfoId', {'id': row['infoId']})
    finally:
        client.close()
    booking = json.loads((ROOT / 'config/booking_data.json').read_text(encoding='utf-8'))
    values = {v['propertyColumnCode']: v['propertyValue'] for v in booking['formManagePropertyValueList']}
    fields = form.get('managePropertyConifgVos')
    if not isinstance(fields, list):
        raise ValueError('表单返回格式变化，停止提交')
    mapped = []
    for field in fields:
        code = field['propertyColumnCode']
        if code not in values:
            raise ValueError('该场地存在尚未配置的表单字段：' + code)
        mapped.append({'propertyId': field['propertyId'], 'propertyColumnCode': code, 'propertyValue': values[code]})
    booking.update(infoId=row['infoId'], location=row['location'],
                   occupyTimeStart=f'{date} {start}:00', occupyTimeEnd=f'{date} {end}:00',
                   formManagePropertyValueList=mapped)
    report = {'configuration': {'venue': row['name'], 'infoId': row['infoId'], 'date': date, 'start': start, 'end': end},
              'liveValidation': {'resource': True, 'configuredSlot': True, 'form': True},
              'note': '配置时段校验通过；实际占用、开放日期与账号限制由预约服务器判断。'}
    report['submission'] = run(credentials, submit=True, booking_data=booking) if submit else {'outcome': 'not_submitted'}
    return report


if __name__ == '__main__':
    from .compat import booking_main
    raise SystemExit(booking_main())
