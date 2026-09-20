"""Python port of the downloaded 303c6e9 loader's deterministic source builder.

The generated JavaScript is data: this module never evaluates it or opens a browser.
"""
import json
from pathlib import Path

ASSETS = Path(__file__).parent / 'assets/loader-literals.json'


class PRNG:
    def __init__(self, seed):
        self.seed = seed

    def __call__(self):
        self.seed = 0x3D3F * (self.seed & 65535) + 0x269EC3
        return self.seed


def shuffle(values, rng):
    for i in range(len(values) - 1, 0, -1):
        j = rng() % i
        values[i], values[j] = values[j], values[i]


class Loader:
    def __init__(self, nsd, literals=None):
        if literals is None:
            literals = json.loads(ASSETS.read_text(encoding='utf-8'))
        self.main, self.extra = [x['value'] for x in literals if x['left'] == '_$el']
        self.source = self.main
        self.position = 0
        self.nsd = nsd
        self.rng = PRNG(nsd)
        chars = '_$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        self.names = ['_$' + chars[i // 64] + chars[i % 64] for i in range(909)]
        shuffle(self.names, PRNG(nsd & 65535))
        self.dispatch_tables = []

    def read(self):
        result = ord(self.source[self.position])
        self.position += 1
        return result

    def read_string(self, size):
        start = self.position
        self.position += size
        return self.source[start:self.position]

    def read_array(self):
        return [self.read() for _ in range(self.read())]

    def template(self, codes):
        out = []
        for i in range(0, len(codes) - 1, 2):
            out.extend([self.tokens[codes[i]], self.names[codes[i + 1]]])
        out.append(self.tokens[codes[-1]])
        return ''.join(out)

    def build(self):
        self.read(); self.read()
        self.global_index, self.table_index = self.read(), self.read()
        self.read()
        token_count = self.read()
        size = self.read() * 55295 + self.read()
        self.tokens = self.read_string(size).split(chr(257)) if token_count else []
        for _ in range(self.read()):
            size = self.read() * 55295 + self.read()
            self.tokens.append(self.read_string(size))
        count = self.read()
        out = []
        for module in range(count):
            out.append('\n' * (self.rng() % 5))
            out.append(self.module(module))
        out.append('}}}}}}}}}}'[count - 1:])
        self.source, self.position = self.extra, 0
        self.read()
        self.tokens = self.read_string(self.read()).split(chr(257))
        out.append(self.template(self.read_array()))
        out.append('})($_ts.scj,$_ts.aebi);')
        return ''.join(out)

    def module(self, index):
        b9, lD, il, fQ, bT, b_dollar, cS, bp = [self.read() for _ in range(8)]
        params, locals_, pairs = self.read_array(), self.read_array(), self.read_array()
        pairs = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
        shuffle(pairs, self.rng)
        branch_limit = self.read()
        self.dispatch_tables.append(self.read_array())
        declarations = [self.read_array() for _ in range(self.read())]
        shuffle(declarations, self.rng)
        instructions = [self.read_array() for _ in range(self.read())]
        names, out = self.names, []
        emit = lambda *s: out.extend(str(x) for x in s)
        if index == 0:
            emit('(function(', names[self.global_index], ',', names[self.table_index], '){var ', names[lD], '=0;')
        else:
            emit('function ', names[bT], '(', names[lD])
            for p in params:
                emit(',', names[p])
            emit('){')
        for name, offset in pairs:
            emit('function ', names[name], '(){var ', names[fQ], '=[', offset,
                 '];Array.prototype.push.apply(', names[fQ], ',arguments);return ',
                 names[b_dollar], '.apply(this,', names[fQ], ');}')
        for codes in declarations:
            emit(self.template(codes))
        if locals_:
            emit('var ', ','.join(names[p] for p in locals_), ';')
        emit('var ', names[il], ',', names[cS], ',', names[b9], '=', names[lD], ',',
             names[bp], '=', names[self.table_index], '[', index, '];')
        spacing_rng = PRNG(self.nsd)
        def spacing():
            return spacing_rng() % 10 + 10 if self.nsd & 65536 else 64
        remaining = spacing()
        def instruction(i):
            nonlocal remaining
            remaining -= 1
            if remaining <= 0:
                remaining = spacing()
                if remaining < 64:
                    emit('debugger;')
            codes = instructions[i]
            for j in range(0, len(codes) - 1, 2):
                emit(self.tokens[codes[j]], names[codes[j + 1]])
            if len(codes) % 2:
                emit(self.tokens[codes[-1]])
        def branches(start, end):
            size = end - start
            if not size:
                return
            if size == 1:
                instruction(start)
            elif size <= 4:
                prefix = 'if('
                for i in range(start, end - 1):
                    emit(prefix, names[cS], '===', i, '){')
                    instruction(i)
                    prefix = '}else if('
                emit('}else{'); instruction(end - 1); emit('}')
            else:
                step = next(4 ** j for j in range(1, 7) if size <= 4 ** (j + 1))
                prefix = 'if('
                while start + step < end:
                    emit(prefix, names[cS], '<', start + step, '){')
                    branches(start, start + step)
                    start += step
                    prefix = '}else if('
                emit('}else{'); branches(start, end); emit('}')
        def expressions(start, end):
            size = end - start
            if size == 1:
                instruction(start)
            elif size == 2:
                emit(names[cS], '==', start, '?'); instruction(start); emit(':'); instruction(start + 1)
            else:
                middle = (start + end) // 2
                emit(names[cS], '<', middle, '?'); expressions(start, middle); emit(':'); expressions(middle, end)
        if instructions:
            emit('while(1){', names[cS], '=', names[bp], '[', names[b9], '++];')
            emit('if(', names[cS], '<', branch_limit, '){')
            branches(0, branch_limit)
            emit('}else ')
            if branch_limit < len(instructions):
                expressions(branch_limit, len(instructions))
            emit(';}')
        return ''.join(out)


def source_checksum(source):
    raw = source.encode('utf-16-le', errors='surrogatepass')
    return sum(int.from_bytes(raw[i:i + 2], 'little') for i in range(0, len(raw), 200))


def generate_bootstrap_source(nsd, literals=None):
    return Loader(nsd, literals=literals).build()
