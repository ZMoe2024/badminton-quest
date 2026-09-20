"""Independent parameter primitives recovered from the inspected site version.

Inputs are supplied explicitly; this module neither opens a browser nor submits requests.
Runtime key/configuration material must stay in memory.
"""
from __future__ import annotations
import base64
import struct
import zlib
import math
import re
import random
import time
from urllib.parse import quote, urljoin, urlsplit
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

DEFAULT_ALPHABET = 'qrcklmDoExthWJiHAp1sVYKU3RFMQw8IGfPO92bvLNj.7zXBaSnu0TC6gy_4Ze5d'


def context_from_config(config, alphabet: str = DEFAULT_ALPHABET) -> dict:
    """Select the exact server-supplied fields from the decoded 45-field config.

    ecn_bootstrap.context_from_bootstrap supplies this table from the raw homepage.
    This lower-level function accepts decoded configuration, not cookies or a JWT.
    """
    names = bytes(config[7]).decode('utf-8').split(';')
    if len(names) < 2 or not names[1]:
        raise ValueError('Configuration is missing its request parameter name')
    return {
        'configBlob': bytes(config[2]),
        'key': bytes(config[17]),
        'configId': int(bytes(config[10]).decode('ascii')),
        # Historical key name retained for the verification harness. This is
        # config field 19, not an assumed boot timestamp.
        'bootValue': int(bytes(config[19]).decode('ascii')),
        'alphabet': alphabet,
        'parameterName': names[1],
    }


def length_prefix(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError('Length outside the unsigned 32-bit range')
    if value <= 0x7F:
        return bytes([value])
    if value <= 0x3FFF:
        return (value | 0x8000).to_bytes(2, 'big')
    if value <= 0x1FFFFF:
        return (value | 0xC00000).to_bytes(3, 'big')
    if value <= 0xFFFFFFF:
        return (value | 0xE0000000).to_bytes(4, 'big')
    return b'\xf0' + value.to_bytes(4, 'big')


def pack_bytes(value: bytes) -> bytes:
    return length_prefix(len(value)) + value


def aes_cbc(data: bytes, key: bytes) -> bytes:
    pad = PKCS7(128).padder()
    padded = pad.update(data) + pad.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return enc.update(padded) + enc.finalize()


def custom_base64(data: bytes, alphabet: str) -> str:
    if len(alphabet) != 64 or len(set(alphabet)) != 64:
        raise ValueError('Expected a 64-character alphabet')
    standard = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    return base64.b64encode(data).decode('ascii').rstrip('=').translate(str.maketrans(standard, alphabet))


def huffman_compress(data: bytes) -> bytes:
    """The site's fixed Huffman tree (not zlib/DEFLATE)."""
    nodes = [(1, byte) for byte in range(1, 255)] + [(6, 255), (45, 0)]
    while len(nodes) > 1:
        left, right = nodes[:2]
        del nodes[:2]
        node = (left[0] + right[0], (left[1], right[1]))
        index = next((i for i, item in enumerate(nodes) if node[0] <= item[0]), len(nodes))
        nodes.insert(index, node)
    codes = {}
    def visit(node, code, bits):
        if isinstance(node, int):
            codes[node] = (code, bits)
        else:
            visit(node[0], code << 1, bits + 1)
            visit(node[1], (code << 1) | 1, bits + 1)
    visit(nodes[0][1], 0, 0)
    padding = next(code >> (bits - 8) for _, (code, bits) in sorted(codes.items()) if bits >= 8)
    output = bytearray()
    accumulator = bits = 0
    for byte in data:
        code, count = codes[byte]
        accumulator = (accumulator << count) | code
        bits += count
        while bits >= 8:
            bits -= 8
            output.append((accumulator >> bits) & 255)
            accumulator &= (1 << bits) - 1
    if bits:
        output.append((accumulator << (8 - bits)) | (padding >> bits))
    return bytes(output)


def encode_request_data(payload: bytes, config_blob: bytes, aes_key: bytes, alphabet: str, compress_enabled: bool = False) -> str:
    """Query-parameter mode, including the conditional Huffman branch."""
    compressed = huffman_compress(payload)
    version = 2 if compress_enabled and len(compressed) < len(payload) else 1
    data = bytearray(compressed if version == 2 else payload)
    if len(data) >= 16:
        for index in range(16):
            data[index] ^= config_blob[index]
    encrypted = aes_cbc(bytes(data), aes_key)
    envelope = bytes([version]) + pack_bytes(b'') + pack_bytes(config_blob) + pack_bytes(encrypted)
    protected = struct.pack('>I', zlib.crc32(envelope)) + envelope
    return '0' + custom_base64(protected, alphabet)


def build_payload(query: str, path_crc: int, flags: int, nonce: int, config_id: int, boot_value: int, charset: str = '') -> bytes:
    effective_flags = (flags & ~7) | 16 | 1
    if query:
        effective_flags |= 2
    if charset:
        effective_flags |= 4
    fields = struct.pack('>IHIQ', effective_flags, config_id, boot_value, nonce)
    fields += struct.pack('>I', path_crc)
    if query:
        fields += pack_bytes(query.encode('utf-8'))
    if charset:
        fields += pack_bytes(charset.encode('utf-8'))
    return b'\x0b' + length_prefix(len(fields)) + fields


def request_nonce(now_ms: int, random_fraction: float, previous_counter: int = 0) -> tuple[int, int]:
    if not 0 <= random_fraction < 1:
        raise ValueError('random_fraction must be in [0, 1)')
    seconds = math.ceil(now_ms / 1000)
    counter = seconds if seconds > previous_counter else previous_counter + 1
    nonce = (counter & 0xFFFFFFFF) + math.floor(random_fraction * 1048575) * 4294967296
    return nonce, counter


def clean_query(query: str, parameter_name: str = 'ecnMsZXb') -> str:
    return '&'.join(part for part in query.split('&') if not part.startswith(parameter_name + '='))


def canonical_component(value: str) -> str:
    value = quote(value, safe="~()*!.'-", encoding='utf-8', errors='strict')
    while True:
        decoded = re.sub(r'%([0-9a-fA-F]{2})', lambda m: chr(int(m[1],16)) if 32 <= int(m[1],16) <= 126 else m[0], value)
        if decoded == value:
            return value.upper()
        value = decoded


def generate_parameter(url: str, context: dict, nonce: int, *, flags: int = 800, origin: str = 'https://resm.lzjtu.edu.cn/') -> str:
    """Generate for ordinary same-origin fetch requests in the inspected version.

    `context` contains configBlob/key byte arrays, configId, bootValue and alphabet.
    Explicit flags preserve the caller's request classification.
    """
    parsed = urlsplit(urljoin(origin, url.replace('\\', '/')))
    if (parsed.scheme, parsed.netloc) != (urlsplit(origin).scheme, urlsplit(origin).netloc):
        raise ValueError('Cross-origin request classification requires separate flags and configuration')
    query = clean_query(parsed.query, context.get('parameterName', 'ecnMsZXb'))
    path_crc = zlib.crc32((canonical_component(parsed.path or '/') + canonical_component(query)).encode('utf-8'))
    payload = build_payload(query, path_crc, flags | 1048576, nonce, context['configId'], context['bootValue'])
    return encode_request_data(payload, bytes(context['configBlob']), bytes(context['key']), context['alphabet'])


class ParameterGenerator:
    """An in-memory generator that keeps the per-request counter across calls."""
    def __init__(self, context: dict, previous_counter: int = 0):
        self.context = dict(context)
        self.counter = previous_counter

    def generate(self, url: str, *, flags: int = 800, now_ms: int | None = None,
                 random_fraction: float | None = None) -> str:
        now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
        random_fraction = random.random() if random_fraction is None else random_fraction
        nonce, counter = request_nonce(now_ms, random_fraction, self.counter)
        result = generate_parameter(url, self.context, nonce, flags=flags)
        self.counter = counter
        return result
