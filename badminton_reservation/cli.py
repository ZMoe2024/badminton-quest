"""Unified command line. Queries and validation never submit a booking."""
import argparse
import json
import sys
from pathlib import Path
from .badminton import CATALOG, refresh
from .venue_catalog import inspect_venue, select_resource
from .workflow import authenticate, book, DEFAULT_SESSION

from .runtime import data_root
ROOT = data_root(__file__)


def authenticated_inputs(args):
    return authenticate(credentials_file=args.credentials_file, session_file=args.session_file,
                        force_renew=getattr(args, 'renew', False), import_session=args.command == 'auth-import')


def dispatch(args):
    if args.command == 'list':
        rows = json.loads(CATALOG.read_text(encoding='utf-8'))['courts']
        rows = [r for r in rows if args.keyword in r['location']]
        return {'count': len(rows), 'courts': [
            {k: row[k] for k in ('name', 'location', 'infoId')} for row in rows]}
    if args.command in ('check', 'submit'):
        return book(args.config, submit=args.command == 'submit',
                    credentials_file=args.credentials_file, session_file=args.session_file,
                    pay_after=getattr(args, 'pay_after', False), expected_amount=getattr(args, 'expected_amount', None))
    credentials, status = authenticated_inputs(args)
    if args.command == 'order':
        from .payment import resolve_order
        record = json.loads(args.booking_record.read_text(encoding='utf-8-sig'))
        return {'order': resolve_order(credentials, record.get('submission', record)), 'authentication': status}
    if args.command == 'pay':
        from .payment import pay
        config = json.loads(args.order_config.read_text(encoding='utf-8-sig'))
        result = pay(credentials, config, submit=args.submit)
        return {'payment': result, 'authentication': status}
    if args.command in ('auth-import', 'auth-check'):
        return {'authentication': status, 'bookingSubmitted': False,
                'sessionStored': status['sessionStored']}
    if args.command == 'refresh':
        return refresh(credentials)
    rows = json.loads(CATALOG.read_text(encoding='utf-8'))['courts']
    return inspect_venue(credentials, select_resource(rows, args.venue), args.date)


def main(argv=None):
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='羽毛球预约：列场地、查时段、校验配置、单次提交')
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list', help='离线列出羽毛球场地')
    listing.add_argument('--keyword', default='')
    for command, help_text in [('refresh', '联网更新羽毛球目录'), ('inspect', '查询指定场地和日期'),
                               ('check', '联网校验预约配置，不提交'), ('submit', '校验后正式提交一次'),
                               ('auth-import', '导入并加密保存登录会话'), ('auth-check', '检查或续期会话，不预约'),
                               ('order', '根据已保存的预约记录查询并保存缴费订单，不预约、不支付'),
                               ('pay', '核对缴费订单；加 --submit 发送一次真实校园卡支付请求')]:
        child = commands.add_parser(command, help=help_text)
        group = child.add_mutually_exclusive_group() if command != 'auth-import' else child
        group.add_argument('--credentials-file', help='凭据JSON文件；- 从标准输入读取')
        group.add_argument('--session-file', type=Path, help='本机加密会话文件；Windows 默认 session.dpapi，macOS 默认 session.keychain（config 目录）')
        if command in ('auth-check', 'auth-import'):
            child.add_argument('--renew', action='store_true', help='立即验证一次CAS续期，即使当前预约Token仍有效')
        if command == 'inspect':
            child.add_argument('--venue', required=True)
            child.add_argument('--date', required=True)
        if command in ('check', 'submit'):
            child.add_argument('--config', type=Path, default=ROOT / 'config/booking.json')
        if command == 'submit':
            child.add_argument('--pay', dest='pay_after', action='store_true', help='预约创建后立即发送一次真实校园卡支付请求')
            child.add_argument('--expected-amount', help='可选：限定金额（元）；不填则读取本次订单金额，支付前复核')
        if command == 'order':
            child.add_argument('--booking-record', type=Path, required=True)
        if command == 'pay':
            child.add_argument('--order-config', type=Path, required=True, help='预约流程输出的 order.orderConfigFile；明确指定原订单')
            child.add_argument('--submit', action='store_true', help='发送一次真实支付请求，有余额时可能实际扣款')
    args = parser.parse_args(argv)
    try:
        report = dispatch(args)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        outcome = report.get('payment', report.get('submission', {})).get('outcome')
        if outcome in ('rejected', 'insufficient_balance', 'expired_or_cancelled'): return 2
        if outcome == 'unknown': return 3
        return 1 if report.get('errors') else 0
    except Exception as exc:
        # Network exceptions may contain the full signed URL. Never print those.
        message = str(exc) if isinstance(exc, ValueError) else '执行失败，请检查配置和凭据；提交后失败须先核实记录，不自动重试'
        print(json.dumps({'errorType': type(exc).__name__, 'message': message}, ensure_ascii=False))
        return 1
