"""List badminton courts, refresh their directory, or inspect date-specific rules."""
import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from .resm_api import ResourceAPI
from .query_scope import borrow_client
from .venue_catalog import DEFAULT_OUTPUT, TREE_QUERY, flatten, inspect_venue, read_credentials, save_json, select_resource

CATALOG = DEFAULT_OUTPUT / 'badminton-courts.json'


def write_badminton(nodes):
    rows = [r for r in nodes if r['infoStatus'] == '1' and '羽毛球' in r['name']]
    result = {'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'count': len(rows),
              'locationCounts': dict(Counter(r['location'].rsplit('>', 1)[0] for r in rows)), 'courts': rows}
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    save_json(CATALOG, result)
    lines = ['# 羽毛球场地目录', '', '状态标记为1的场地；实际时段和账号预约条件需实时查询。', '',
             '| 场地 | 完整位置 | 预约用 infoId |', '| --- | --- | --- |']
    lines.extend(f"| {r['name']} | {r['location']} | `{r['infoId']}` |" for r in rows)
    (DEFAULT_OUTPUT / '羽毛球场地目录.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {k: v for k, v in result.items() if k != 'courts'}


def refresh(credentials):
    with borrow_client(credentials, ResourceAPI) as client:
        tree = client.post_query('/hzsun-resm/resourcetree/queryResourceTree', TREE_QUERY)
        return write_badminton(flatten(tree['resourceTreeVos']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list', 'refresh', 'inspect'], nargs='?', default='list')
    parser.add_argument('--keyword', default='')
    parser.add_argument('--venue')
    parser.add_argument('--date')
    parser.add_argument('--credentials-file', default='-')
    args = parser.parse_args()
    if args.command == 'refresh': return refresh(read_credentials(args.credentials_file))
    courts = json.loads(CATALOG.read_text(encoding='utf-8'))['courts']
    if args.command == 'list':
        rows = [r for r in courts if args.keyword in r['location']]
        return {'count': len(rows), 'courts': [{'name': r['name'], 'location': r['location'], 'infoId': r['infoId']} for r in rows]}
    if not args.venue or not args.date: raise ValueError('inspect 需要 --venue 和 --date')
    row = select_resource(courts, args.venue)
    return inspect_venue(read_credentials(args.credentials_file), row, args.date)


if __name__ == '__main__':
    from .compat import catalog_main
    raise SystemExit(catalog_main())
