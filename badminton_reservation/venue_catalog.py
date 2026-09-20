"""Export/search resource IDs and inspect venue rules using Python HTTP."""
import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from .resm_api import ResourceAPI

DEFAULT_OUTPUT = Path(__file__).parent / 'state/venues'
TREE_QUERY = {'infoStatus': '0', 'resFlag': '1', 'resName': '', 'resType': '', 'userFlag': '', 'userId': ''}


def flatten(nodes, ancestors=()):
    rows = []
    for node in nodes:
        path = ancestors + (node['name'],)
        rows.append({'name': node['name'], 'infoId': node['id'], 'resTypeId': node.get('resTypeId'),
                     'parentId': node.get('parentResId'), 'category': path[0], 'location': '>'.join(path),
                     'infoStatus': str(node.get('infoStatus', '')), 'level': node.get('infoLevel'),
                     'isLeaf': not bool(node.get('children')), 'disabled': node.get('disabled'),
                     'viewFlag': node.get('viewFlag')})
        rows.extend(flatten(node.get('children') or [], path))
    return rows


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def export_catalog(credentials, output=DEFAULT_OUTPUT):
    client = ResourceAPI(credentials)
    try:
        groups = client.post_query('/hzsun-resm/resmanageinfo/queryList', {'type': 'res'})
        tree = client.post_query('/hzsun-resm/resourcetree/queryResourceTree', TREE_QUERY)
        return write_catalog(groups, tree, output)
    finally:
        client.close()


def write_catalog(groups, tree, output=DEFAULT_OUTPUT):
    output.mkdir(parents=True, exist_ok=True)
    nodes = flatten(tree['resourceTreeVos'])
    if len({row['infoId'] for row in nodes}) != len(nodes):
        raise ValueError('资源树存在重复ID，停止覆盖目录')
    resources = [row for row in nodes if row['infoStatus'] == '1']
    sports = [row for row in resources if row['category'] == '体育场馆']
    report = {'fetchedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'source': 'Python requests',
              'nodeCount': len(nodes), 'resourceCount': len(resources), 'sportsCount': len(sports),
              'categoryCounts': dict(Counter(row['category'] for row in resources)),
              'overviewResourceCount': sum(int(group['resTotalCount']) for group in groups),
              'note': 'infoStatus=1与资源总览计数对应；实际账号权限、时段、预约次数仍由服务器判断。'}
    report['countsMatchOverview'] = report['resourceCount'] == report['overviewResourceCount']
    save_json(output / 'resource-tree.json', tree)
    save_json(output / 'resource-groups.json', groups)
    save_json(output / 'all-nodes.json', nodes)
    save_json(output / 'resources.json', {'metadata': report, 'resources': resources})
    save_json(output / 'sports-venues.json', sports)
    save_json(output / 'catalog-summary.json', report)
    lines = ['# 体育场馆资源目录', '',
             '按接口 infoStatus=1 筛选。列出资源不代表当前账号、日期和时段一定可预约。', '',
             '| 场地完整位置 | 预约用 infoId |', '| --- | --- |']
    lines.extend(f"| {row['location']} | `{row['infoId']}` |" for row in sports)
    (output / '体育场馆目录.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report


def load_resources(output=DEFAULT_OUTPUT):
    return json.loads((output / 'resources.json').read_text(encoding='utf-8'))['resources']


def select_resource(rows, selector):
    exact = [r for r in rows if selector in (r['infoId'], r['location'])]
    if not exact: exact = [r for r in rows if r['name'] == selector]
    if len(exact) != 1:
        raise ValueError('场地不存在或名称重名；请使用目录中的完整位置或 infoId')
    return exact[0]


def inspect_venue(credentials, row, date, output=DEFAULT_OUTPUT):
    dt.date.fromisoformat(date)
    info_id = row['infoId']
    queries = [
        ('detail', '/resmanageinfo/queryResInfo', {'resId': info_id}),
        ('rules', '/subManageTimeConfig/queryManageTimeConfigRuleByResId', {'id': info_id}),
        ('timeBlocks', '/subManageTimeConfig/selectTimeBlock', {'infoId': info_id, 'dateTime': date}),
        ('form', '/formManageConifg/selectByInfoId', {'id': info_id}),
    ]
    client = ResourceAPI(credentials)
    result = {'venue': row, 'date': date, 'fetchedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'queries': {}, 'errors': {}}
    try:
        for name, path, params in queries:
            try:
                value = client.query('/hzsun-resm' + path, params)
                if name == 'rules' and isinstance(value, dict):
                    value.pop('loginUsers', None)
                result['queries'][name] = value
            except ValueError as exc:
                result['errors'][name] = str(exc)
        output.mkdir(parents=True, exist_ok=True)
        destination = output / (info_id + '-' + date + '.json')
        save_json(destination, result)
        return {'venue': row['location'], 'date': date, 'saved': str(destination),
                'queries': {name: {'type': type(value).__name__, 'keys': list(value) if isinstance(value, dict) else [],
                                   'count': len(value) if isinstance(value, list) else None} for name, value in result['queries'].items()},
                'errors': result['errors']}
    finally:
        client.close()


def read_credentials(path):
    if not path: raise ValueError('联网查询需要 --credentials-file；传 - 可从标准输入读取')
    return json.load(sys.stdin) if path == '-' else json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['export', 'list', 'inspect'], nargs='?', default='export')
    parser.add_argument('--credentials-file', default='-')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--keyword', default='')
    parser.add_argument('--category', default='')
    parser.add_argument('--venue')
    parser.add_argument('--date')
    args = parser.parse_args()
    if args.command == 'export':
        return export_catalog(read_credentials(args.credentials_file), args.output)
    rows = load_resources(args.output)
    if args.command == 'list':
        rows = [r for r in rows if args.keyword in r['location'] and (not args.category or r['category'] == args.category)]
        return {'count': len(rows), 'resources': rows}
    if not args.venue or not args.date: raise ValueError('inspect 需要 --venue 和 --date')
    return inspect_venue(read_credentials(args.credentials_file), select_resource(rows, args.venue), args.date, args.output)


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8'); sys.stdout.reconfigure(encoding='utf-8')
    try: print(json.dumps(main(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({'errorType': type(exc).__name__, 'message': str(exc) if isinstance(exc, ValueError) else '资源读取失败'}, ensure_ascii=False))
        raise SystemExit(1)
