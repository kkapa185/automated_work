"""SQL tokenizer. Produces a list of Tok ending with an 'eof' token.

If an unrecognized token is met, a 'bad' token is emitted (and tokenizing stops) so that
statements preceding the bad text can still be executed.
"""
import re
from .values import INT_MAX


class Tok:
    __slots__ = ('kind', 'val', 'up', 'start', 'end')

    def __init__(self, kind, val, start, end):
        self.kind = kind
        self.val = val
        self.up = val.upper() if kind == 'id' else None
        self.start = start
        self.end = end

    def __repr__(self):
        return 'Tok(%s,%r)' % (self.kind, self.val)


_TOKEN_RE = re.compile(r'''
 (?P<ws>[ \t\n\r\f]+|--[^\n]*|/\*.*?(?:\*/|\Z))
|(?P<blob>[xX]'[0-9a-fA-F]*')
|(?P<id>[A-Za-z_\u0080-\U0010FFFF][A-Za-z0-9_$\u0080-\U0010FFFF]*)
|(?P<num>0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
|(?P<str>'(?:[^']|'')*')
|(?P<qid>"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]*\])
|(?P<var>\?\d*|[:@$][A-Za-z_][A-Za-z0-9_]*)
|(?P<op>\|\||<<|>>|<=|>=|==|!=|<>|->>|->|[-+*/%&|~<>=(),.;])
''', re.X | re.S)


def tokenize(src):
    toks = []
    pos = 0
    n = len(src)
    match = _TOKEN_RE.match
    while pos < n:
        m = match(src, pos)
        if not m:
            c = src[pos]
            if c in '\'"`':
                text = src[pos:]
            elif c == '[':
                text = src[pos:]
            else:
                text = c
            toks.append(Tok('bad', text, pos, n if len(text) > 1 else pos + 1))
            pos = n
            break
        kind = m.lastgroup
        end = m.end()
        if kind == 'ws':
            pos = end
            continue
        text = m.group()
        if kind == 'id':
            toks.append(Tok('id', text, pos, end))
        elif kind == 'num':
            if text[:2] in ('0x', '0X'):
                v = int(text, 16)
                if v > (1 << 64) - 1:
                    toks.append(Tok('bad', text, pos, end))
                    pos = n
                    break
                if v > INT_MAX:
                    v -= 1 << 64
                toks.append(Tok('int', v, pos, end))
            elif '.' in text or 'e' in text or 'E' in text:
                toks.append(Tok('float', float(text), pos, end))
            else:
                v = int(text)
                if v > INT_MAX:
                    toks.append(Tok('float', float(text), pos, end))
                    toks[-1].up = 'BIG'  # marks integer literal that overflowed
                else:
                    toks.append(Tok('int', v, pos, end))
            # a number directly followed by identifier characters is malformed
            if end < n and (src[end].isalpha() or src[end] == '_'):
                toks[-1] = Tok('bad', src[pos:end + 1], pos, end + 1)
                pos = n
                break
        elif kind == 'str':
            toks.append(Tok('str', text[1:-1].replace("''", "'"), pos, end))
        elif kind == 'qid':
            q = text[0]
            if q == '[':
                v = text[1:-1]
            else:
                v = text[1:-1].replace(q + q, q)
            toks.append(Tok('qid', v, pos, end))
        elif kind == 'blob':
            h = text[2:-1]
            if len(h) % 2:
                toks.append(Tok('bad', text, pos, end))
                pos = n
                break
            toks.append(Tok('blob', bytes.fromhex(h), pos, end))
        elif kind == 'var':
            toks.append(Tok('var', text, pos, end))
        else:
            toks.append(Tok('op', text, pos, end))
        pos = end
    toks.append(Tok('eof', '', n, n))
    return toks
