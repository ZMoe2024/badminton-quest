"""Extract data literals from the current JavaScript loader without executing it."""
from collections import defaultdict
import hashlib
import re
from .ecn_bootstrap import BootstrapError

IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')


def read_string(source, start):
    quote = source[start]
    out, position = [], start + 1
    escapes = {'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v'}
    while position < len(source):
        char = source[position]
        position += 1
        if char == quote:
            return ''.join(out), position
        if char in '\r\n':
            raise BootstrapError('防护模板中存在未转义换行')
        if char != '\\':
            # JavaScript string indexing uses UTF-16 code units.
            raw = char.encode('utf-16-le', errors='surrogatepass')
            out.extend(chr(int.from_bytes(raw[i:i+2], 'little')) for i in range(0, len(raw), 2))
            continue
        if position >= len(source): break
        char = source[position]
        position += 1
        if char in escapes:
            out.append(escapes[char])
        elif char in '\r\n':
            if char == '\r' and position < len(source) and source[position] == '\n': position += 1
        elif char in 'xu':
            width = 2 if char == 'x' else 4
            digits = source[position:position+width]
            if len(digits) != width or any(c not in '0123456789abcdefABCDEF' for c in digits):
                raise BootstrapError('防护模板使用了未支持的字符串转义')
            out.append(chr(int(digits, 16))); position += width
        elif char in '01234567':
            digits = char
            limit = 3 if char in '0123' else 2
            while len(digits) < limit and position < len(source) and source[position] in '01234567':
                digits += source[position]; position += 1
            out.append(chr(int(digits, 8)))
        else:
            out.append(char)
    raise BootstrapError('防护模板字符串不完整')


def extract_templates(content):
    if len(content) > 8 * 1024 * 1024:
        raise BootstrapError('防护脚本大小超出支持范围')
    try: source = content.decode('utf-8-sig')
    except UnicodeError: raise BootstrapError('防护脚本不是UTF-8文本') from None
    groups = defaultdict(list)
    recent, position = [], 0
    while position < len(source):
        char = source[position]
        if char.isspace(): position += 1; continue
        if source.startswith('//', position):
            end = source.find('\n', position + 2)
            position = len(source) if end < 0 else end + 1
            continue
        if source.startswith('/*', position):
            end = source.find('*/', position + 2)
            if end < 0: raise BootstrapError('防护脚本注释不完整')
            position = end + 2
            continue
        if char == '/' and (not recent or recent[-1] in ('=', '(', '[', ',', ':', '!', 'return', 'case', ';', '{')):
            position += 1
            in_class, closed = False, False
            while position < len(source):
                value = source[position]; position += 1
                if value == '\\': position += 1; continue
                if value in '\r\n': break
                if value == '[': in_class = True
                elif value == ']': in_class = False
                elif value == '/' and not in_class:
                    closed = True
                    while position < len(source) and source[position].isalpha(): position += 1
                    break
            if not closed: raise BootstrapError('防护脚本正则字面量不完整')
            recent = (recent + ['<regex>'])[-2:]
            continue
        if char in "\"'":
            value, position = read_string(source, position)
            if len(value) > 200 and len(recent) == 2 and recent[1] == '=' and IDENTIFIER.fullmatch(recent[0]):
                groups[recent[0]].append(value)
            recent = (recent + ['<string>'])[-2:]
            continue
        if char == '`':
            raise BootstrapError('防护脚本包含尚未支持的模板字面量')
        identifier = IDENTIFIER.match(source, position)
        if identifier:
            token = identifier.group(); position = identifier.end()
        else:
            token = char; position += 1
        recent = (recent + [token])[-2:]
    candidates = [values for values in groups.values()
                  if len(values) == 2 and len(values[0]) > 10000 and 200 < len(values[1]) < 10000]
    if len(candidates) != 1:
        raise BootstrapError('不能唯一识别当前防护脚本的两段模板，脚本结构需要适配')
    # The loader consumes only these two strings; source variable names are irrelevant.
    literals = [{'left': '_$el', 'value': value} for value in candidates[0]]
    digest = hashlib.sha256(content.replace(b'\r\n', b'\n')).hexdigest()
    return literals, digest
