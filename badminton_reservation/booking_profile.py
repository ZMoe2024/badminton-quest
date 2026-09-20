"""Editable booking contact; never changes the authenticated account identity."""
import json
import os
from pathlib import Path
import re
import tempfile

PATH = Path(__file__).resolve().parent / 'config/booking_data.json'


def load_phone():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    return next((str(row.get('propertyValue', '')) for row in data['formManagePropertyValueList']
                 if row['propertyColumnCode'] == 'LXDH'), '')


def require_phone():
    if not load_phone().strip():
        raise ValueError('请先到登录设置填写并保存自己的联系电话。')


def save_phone(phone):
    if not isinstance(phone, str) or not re.fullmatch(r'\+?[0-9]{7,15}', phone.strip()):
        raise ValueError('请填写7至15位数字联系电话，可带国际区号前缀 +。')
    data = json.loads(PATH.read_text(encoding='utf-8'))
    field = next((row for row in data['formManagePropertyValueList'] if row['propertyColumnCode'] == 'LXDH'), None)
    if field is None:
        raise ValueError('预约配置缺少联系电话字段，请恢复发布包的表单配置。')
    field['propertyValue'] = phone.strip()
    fd, temp = tempfile.mkstemp(prefix='contact-', suffix='.tmp', dir=PATH.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, PATH)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
