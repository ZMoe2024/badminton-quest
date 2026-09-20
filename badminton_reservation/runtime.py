"""Process-scoped data paths; server workers never share user state."""
import datetime as dt
import json
import os
from pathlib import Path
import shutil


def data_root(module_file):
    value = os.environ.get('BADMINTON_DATA_DIR')
    return Path(value).resolve() if value else Path(module_file).resolve().parent


def initialize_user(root):
    root = Path(root)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    defaults = {
        'config/booking.json': {'venue': '主馆羽毛球场11', 'date': today, 'start': '10:00', 'end': '12:00'},
        'config/booking_data.json': {'applyRemark': '', 'infoId': '', 'occupyId': '',
            'occupyTimeStart': '', 'occupyTimeEnd': '', 'occupyType': '1', 'resUseType': '0',
            'timeChooseType': '2', 'isInvite': '0', 'location': '', 'msgLeadTime': [],
            'leaveUsers': [], 'auditUserIds': [], 'formManagePropertyValueList': [
                {'propertyId': '', 'propertyColumnCode': 'LXDH', 'propertyValue': ''}]},
        'state/automation/tasks.json': {'version': 1, 'jobs': {}}}
    for name, value in defaults.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        if not file.exists():
            with file.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
    catalog = root / 'state/venues/badminton-courts.json'
    if not catalog.exists():
        catalog.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parent / 'state/venues/badminton-courts.json', catalog)
