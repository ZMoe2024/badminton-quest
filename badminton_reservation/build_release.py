"""Build an allowlisted, credential-free source ZIP for Windows and macOS."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = '0.7.2'
PACKAGE = 'BadmintonQuest-' + VERSION
MODULES = '''__init__ __main__ automation availability badminton badminton_booking
booking_submit_python cli compat ecn_bootstrap ecn_bootstrap_loader ecn_client
ecn_parameter fetch_bootstrap gui_server launcher loader_templates payment resm_api
response run session session_store start_gui venue_catalog workflow browser_login booking_profile'''.split()
GUI_FILES = ['index.html', 'app.js', 'automation.js', 'login.js', 'style.css', 'dashboard.css',
             'assets/concept.png', 'assets/gym.png']


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def payloads():
    files = {name + '.py': (ROOT / (name + '.py')).read_bytes() for name in MODULES}
    for name in ['requirements.txt', 'Start-Windows.bat', 'Start-macOS.command']:
        files[name] = (ROOT / name).read_bytes()
    # macOS executable scripts must have LF newlines even when built on Windows.
    files['Start-macOS.command'] = files['Start-macOS.command'].replace(b'\r\n', b'\n')
    files['README.md'] = (ROOT / 'docs/DISTRIBUTION.md').read_bytes()
    for name in GUI_FILES:
        files['gui/' + name] = (ROOT / 'gui' / name).read_bytes()
    for name in ['loader-literals.json', 'loader-literals-db58ba62.json']:
        files['assets/' + name] = (ROOT / 'assets' / name).read_bytes()
    for path in sorted((ROOT / 'tests').glob('test_*.py')):
        files['tests/' + path.name] = path.read_bytes()
    # Generate clean defaults. Never copy local config files or personal state.
    files['config/booking.json'] = json_bytes({'venue': '主馆羽毛球场11',
        'date': dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat(),
        'start': '10:00', 'end': '12:00'})
    files['config/booking_data.json'] = json_bytes({
        'applyRemark': '', 'infoId': '', 'occupyId': '', 'occupyTimeStart': '', 'occupyTimeEnd': '',
        'occupyType': '1', 'resUseType': '0', 'timeChooseType': '2', 'isInvite': '0', 'location': '',
        'msgLeadTime': [], 'leaveUsers': [], 'auditUserIds': [],
        'formManagePropertyValueList': [{'propertyId': '', 'propertyColumnCode': 'LXDH', 'propertyValue': ''}]})
    files['config/credentials.example.json'] = json_bytes({
        'cookie': '替换为预约网站 Cookie 请求头', 'token': '替换为 X-Access-Token',
        'currentUser': '替换为 sessionStorage.currentUser 原始值',
        'userAgent': '替换为采集时浏览器 User-Agent', 'ssoCookies': []})
    source = json.loads((ROOT / 'state/venues/badminton-courts.json').read_text(encoding='utf-8'))
    keys = ('name', 'infoId', 'resTypeId', 'parentId', 'category', 'location', 'infoStatus',
            'level', 'isLeaf', 'disabled', 'viewFlag')
    courts = [{key: row[key] for key in keys} for row in source['courts']]
    files['state/venues/badminton-courts.json'] = json_bytes({
        'updatedAt': source['updatedAt'], 'count': len(courts), 'courts': courts})
    files['state/automation/tasks.json'] = json_bytes({'version': 1, 'jobs': {}})
    files['MANIFEST.json'] = json_bytes({'version': VERSION, 'files': {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}})
    return files


def build():
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    destination = output / (PACKAGE + '-Windows-macOS.zip')
    files = payloads()
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(PACKAGE + '/badminton_reservation/' + name)
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith('.command') else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(digest + '  ' + destination.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(destination), 'files': len(files), 'bytes': destination.stat().st_size,
                      'sha256': digest}, indent=2))
    return destination


if __name__ == '__main__':
    build()
