"""Decode raw or JSON-wrapped business responses."""
import base64
import json

def unpack_body(body):
    try:
        value = json.loads(body)
        if not isinstance(value, str):
            raise ValueError('需要抓包中的原始混淆 Body，而不是明文对象')
        body = value
    except json.JSONDecodeError:
        pass
    encoded = ''.join(body[13:-6].split())
    return json.loads(base64.b64decode(encoded, validate=True).decode('utf-8'))


def decode_result(text):
    for _ in range(4):
        if not isinstance(text, str):
            return text
        try:
            text = json.loads(text)
            continue
        except json.JSONDecodeError:
            pass
        try:
            text = unpack_body(text)
        except (ValueError, UnicodeError):
            return None
    return text if isinstance(text, dict) else None


