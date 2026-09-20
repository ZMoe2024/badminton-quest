"""Decode the server bootstrap without browser state or a JavaScript engine."""
from __future__ import annotations
import base64
import struct

from .ecn_bootstrap_loader import PRNG, generate_bootstrap_source, source_checksum
from .ecn_parameter import DEFAULT_ALPHABET, context_from_config


class BootstrapError(ValueError):
    pass


def decode_base64(value):
    standard = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    translated = value.translate(str.maketrans(DEFAULT_ALPHABET, standard))
    return base64.b64decode(translated + '=' * (-len(translated) % 4), validate=True)


def decode_patch(data, checksum):
    data = bytearray(data)
    rng = PRNG(checksum)
    mask = b''.join(struct.pack('>I', rng()) for _ in range(4))
    for start in range(20, len(data), 16):
        size = min(len(data) - start, 16)
        offset = start % size
        data[start + offset] ^= mask[offset]
    text = data.decode('utf-8')
    units = list(struct.unpack('<' + 'H' * (len(text.encode('utf-16-le')) // 2), text.encode('utf-16-le')))
    if len(units) < 2:
        raise BootstrapError('Truncated configuration program')
    count, position = units[1], 2
    programs = {}
    for _ in range(count):
        if position + 3 > len(units):
            raise BootstrapError('Truncated function header')
        index, _unused, length = units[position:position + 3]
        position += 3
        if not 8 <= index <= 20 or position + length > len(units):
            raise BootstrapError('Unsupported configuration function layout')
        programs[index] = units[position:position + length]
        position += length
    if position != len(units):
        raise BootstrapError('Unexpected trailing configuration program')
    return programs


class ConfigVM:
    """Bounded arithmetic bytecode interpreter; no I/O or JavaScript evaluation."""
    def __init__(self, programs):
        self.programs = programs
        self.steps = 0

    def run(self, index, arguments, depth=0):
        if depth > 30:
            raise BootstrapError('Configuration call depth exceeded')
        if index == 21:
            return abs(arguments[0]) % 8
        if index not in range(8, 21):
            raise BootstrapError('Unsupported configuration call')
        default = [38, 0, 34] if index != 20 else sum(([19, 14, i] for i in range(8, 20)), [])
        code = self.programs.get(index, default)
        args, local, stack = list(arguments), {}, []
        position = 0
        def read():
            nonlocal position
            value = code[position]
            position += 1
            return value
        def reference():
            kind = read()
            if kind == 5:
                return local, read()
            if kind == 21:
                return args, read()
            if kind == 14:
                return 'global', read()
            if kind == 60:
                key, target = stack.pop(), stack.pop()
                return target, key
            raise BootstrapError(f'Unsupported configuration reference {kind}')
        def call(count, push):
            values = stack[-count:] if count else []
            if count:
                del stack[-count:]
            target, key = reference()
            if target != 'global':
                raise BootstrapError('Unsupported configuration call target')
            result = self.run(key, values, depth + 1)
            if push:
                stack.append(result)
        while position < len(code):
            self.steps += 1
            if self.steps > 10000:
                raise BootstrapError('Configuration instruction limit exceeded')
            op = read()
            if op == 1:
                stack.append(args[read()])
            elif op == 29:
                stack.append(local.get(read()))
            elif op == 38:
                stack.append(read())
            elif op == 10:
                value = stack.pop(); target, key = reference(); target[key] = value
            elif op == 27:
                key, target = stack.pop(), stack.pop(); stack.append(target[key])
            elif op in (43, 4, 69, 113, 94, 12, 51, 18, 44, 53, 110, 83):
                right, left = stack.pop(), stack.pop()
                if op == 43: value = left + right
                elif op == 4: value = left - right
                elif op == 69: value = left * right
                elif op == 113: value = left / right
                elif op == 94: value = left - int(left / right) * right
                elif op == 12: value = left < right
                elif op == 51: value = left > right
                elif op == 18: value = left == right
                elif op == 44: value = left != right
                elif op == 53: value = int(left) & int(right)
                elif op == 110: value = int(left) | int(right)
                else: value = int(left) ^ int(right)
                stack.append(value)
            elif op == 114:
                stack.append(-stack.pop())
            elif op == 39:
                stack.append(not stack.pop())
            elif op in (26, 64):
                delta = read()
                if not stack.pop(): position += delta
            elif op == 59:
                delta = read(); position += delta
            elif op in (7, 31, 61, 68):
                call({7: 1, 31: 2, 61: 0, 68: 3}[op], True)
            elif op in (19, 42, 15, 57):
                call({19: 0, 42: 1, 15: 2, 57: 3}[op], False)
            elif op == 34:
                return stack.pop()
            elif op == 16:
                return None
            else:
                raise BootstrapError(f'Unsupported configuration opcode {op}')
        return None


def configuration_xor_key(programs):
    vm = ConfigVM(programs)
    values = list(range(8))
    # Initial globals are 1, 17, charCodeAt("0", 0); seedStep runs once.
    seed89, seed90, seed91 = 3, 51, 153
    vm.run(20, [values])
    values[0] = seed89 + vm.run(8, [values])
    if values[0] > 10:
        values[1] = seed90 + vm.run(9, [values])
        values[0] = values[1] * vm.run(10, [values])
    else:
        values[1] = seed91 + vm.run(10, [values])
    return bytes(min(255, abs(int(value))) for value in values)


def decode_config(cd, nsd, literals=None):
    source = generate_bootstrap_source(nsd, literals=literals)
    raw = decode_base64(cd)
    if len(raw) < 3:
        raise BootstrapError('Truncated bootstrap')
    patch_length = int.from_bytes(raw[:2], 'big')
    if patch_length > len(raw) - 3:
        raise BootstrapError('Invalid bootstrap program length')
    programs = decode_patch(raw[2:2 + patch_length], source_checksum(source))
    key = configuration_xor_key(programs)
    fields_raw = bytes(value ^ key[i % 8] for i, value in enumerate(raw[2 + patch_length:]))
    position, fields = 1, []
    for _ in range(45):
        if position + 2 > len(fields_raw):
            raise BootstrapError('Truncated configuration field')
        length = int.from_bytes(fields_raw[position:position + 2], 'big')
        position += 2
        if position + length > len(fields_raw):
            raise BootstrapError('Invalid configuration field length')
        fields.append(fields_raw[position:position + length])
        position += length
    if position != len(fields_raw):
        raise BootstrapError('Unexpected trailing configuration fields')
    if len(fields[2]) != 48 or len(fields[17]) != 16:
        raise BootstrapError('Unexpected AES/configuration material format')
    return fields


def context_from_bootstrap(cd, nsd, literals=None):
    return context_from_config(decode_config(cd, nsd, literals=literals))
