"""Read-only availability, using the same occupancy sources as the website."""
import datetime as dt
import json
from .resm_api import ResourceAPI

TZ = dt.timezone(dt.timedelta(hours=8))


def now_local():
    return dt.datetime.now(TZ).replace(tzinfo=None)


def timestamp(value):
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000, TZ).replace(tzinfo=None)
    return dt.datetime.fromisoformat(str(value).replace('/', '-')).replace(tzinfo=None)


def intervals(data, start_key, end_key, label):
    if not isinstance(data, list):
        raise ValueError('网站占用数据格式变化，暂不显示可预约')
    return [(timestamp(r[start_key]), timestamp(r[end_key]), label) for r in data]


def classify_slots(groups, rules, ranges, date, info_id, *, now=None, forced=False):
    now = now or now_local()
    day = dt.date.fromisoformat(date)
    rule = rules['subManageTimeConfigVo']
    horizon = json.loads(rule['useMaxTime']) if isinstance(rule['useMaxTime'], str) else rule['useMaxTime']
    days = int(horizon.get('day', 0)) + bool(horizon.get('hours', 0) or horizon.get('minutes', 0))
    last_day = now.date() + dt.timedelta(days=max(0, days - 1))
    last_opens = dt.time.fromisoformat(rule.get('lastDayOpenTime') or '00:00')
    slots = []
    for group in groups:
        if group.get('infoId') != info_id: continue
        for block in group['resUseTimeBlockInfoList']:
            start, end = block['blockStartTime'], block['blockEndTime']
            a, b = timestamp(date + ' ' + start), timestamp(date + ' ' + end)
            state, label = 'available', '可预约'
            if not int(group['minBlockNum']) <= 1 <= int(group['maxBlockNum']):
                state, label = 'closed', '需组合时段'
            if day > last_day or (day == last_day and now.time() < last_opens):
                state, label = 'closed', '未开放'
            else:
                expiry = b if str(rule.get('isSubBeforeEndTime')) == '1' else a
                if expiry <= now: state, label = 'closed', '已过期'
                for x, y, why in ranges:
                    if x < b and y > a:
                        state, label = ('occupied' if why == '已占用' else 'closed'), why
                if forced: state, label = 'occupied', '已占用'
            if str(block.get('rsrvShareType')) == '2':
                used, maximum = block.get('blockOccupyUsers'), block.get('blockMaxUsers')
                # Shared resources require complete capacity data; don't guess vacancy.
                if used is None or maximum is None: state, label = 'unknown', '待核实容量'
                elif int(used) >= int(maximum): state, label = 'occupied', '已满'
            slots.append({'start': start, 'end': end, 'state': state, 'label': label,
                          'name': block.get('blockName', ''), 'available': state == 'available'})
    return sorted(slots, key=lambda x: x['start'])


def fetch_court(client, row, date, forced_ids=()):
    info_id = row['infoId']
    start, end = date + ' 00:00:00', date + ' 23:59:59'
    q = lambda path, params: client.query('/hzsun-resm' + path, params)
    groups = q('/subManageTimeConfig/selectTimeBlock', {'infoId': info_id, 'dateTime': date})
    rules = q('/subManageTimeConfig/queryManageTimeConfigRuleByResId', {'id': info_id})
    occupy = q('/sub/occupy/queryResUseOccupyByResId', {'id': info_id, 'startDateStr': start, 'endDateStr': end})
    ranges = intervals(occupy, 'occupyTimeStart', 'occupyTimeEnd', '已占用')
    locks = q('/resUseLockTime/queryLockTime', {'infoId': info_id, 'startTime': start, 'endTime': end})
    for lock in locks:
        for a, b in lock['lockTime']: ranges.append((timestamp(a), timestamp(b), '已锁定'))
    freeze = q('/freeze/queryFreezeInfos', {'infoId': info_id, 'startDateStr': start, 'endDateStr': end})
    ranges += intervals(freeze, 'recordStartTime', 'recordEndTime', '已冻结')
    unavailable = q('/resUseTimeInfo/getResUnUseTimeList', {'infoId': info_id, 'startTime': start, 'endTime': end})
    for a, b in unavailable: ranges.append((timestamp(a), timestamp(b), '不可预约'))
    courses = client.post_query('/hzsun-resm/sub/occupy/queryTimetableEmploy',
                               {'infoIds': [info_id], 'startDateStr': start, 'endDateStr': end})
    if not isinstance(courses, list): raise ValueError('课程占用格式变化，请在网站核对')
    for group in courses:
        ranges += intervals(group.get('teachCourseInfoList') or [], 'courseStartTime', 'courseEndTime', '课程占用')
    return {'infoId': info_id, 'name': row['name'], 'slots': classify_slots(
        groups, rules, ranges, date, info_id, forced=info_id in forced_ids)}


def fetch_availability(credentials, rows, date):
    dt.date.fromisoformat(date)
    client = ResourceAPI(credentials)
    try:
        forced = client.query('/hzsun-resm/res/aside/query')
        if not isinstance(forced, list): raise ValueError('网站特殊占用状态查询失败')
        courts = []
        for row in rows:
            try: courts.append(fetch_court(client, row, date, forced))
            except Exception as exc:
                courts.append({'infoId': row['infoId'], 'name': row['name'], 'slots': [],
                               'error': str(exc) if isinstance(exc, ValueError) else '实时查询失败，请刷新后重试'})
        return {'date': date, 'courts': courts, 'fetchedAt': dt.datetime.now(TZ).isoformat(),
                'source': '学校预约网站', 'note': '空闲状态不代表账号一定符合预约次数等限制；提交由学校服务器最终校验。'}
    finally:
        client.close()
