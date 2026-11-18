"""Tokeniser for the jq language."""
import re

KEYWORDS = {"def", "if", "then", "elif", "else", "end", "as", "reduce", "foreach", "try",
            "catch", "label", "import", "include", "and", "or", "__loc__", "module"}


class JQSyntaxError(Exception):
    def __init__(self, msg):
        Exception.__init__(self, msg)
        self.msg = msg


NUM_RE = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z_0-9]*(?:::[a-zA-Z_][a-zA-Z_0-9]*)*")
FIELD_RE = re.compile(r"\.[a-zA-Z_][a-zA-Z_0-9]*")
VAR_RE = re.compile(r"\$(?:__loc__|[a-zA-Z_][a-zA-Z_0-9]*(?:::[a-zA-Z_][a-zA-Z_0-9]*)*)")
FORMAT_RE = re.compile(r"@[a-zA-Z0-9_]+")
OPS3 = ("?//", "//=")
OPS2 = ("|=", "+=", "-=", "*=", "/=", "%=", "//", "==", "!=", "<=", ">=", "..")
OPS1 = ".[]{}()|,:;=<>+-*/%?$"
ESC = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class Tok:
    __slots__ = ("kind", "val", "pos")

    def __init__(self, kind, val, pos):
        self.kind, self.val, self.pos = kind, val, pos

    def __repr__(self):
        return "Tok(%s,%r)" % (self.kind, self.val)


def tokenize(src, i=0, nested=False):
    """Return (tokens, end). With nested=True stop at the unbalanced ')' closing an interpolation."""
    toks = []
    n = len(src)
    depth = 0
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "#":
            # comment: runs to end of line; an odd run of backslashes before newline continues it
            while i < n:
                if src[i] == "\n":
                    k = i - 1
                    bs = 0
                    while k >= 0 and src[k] == "\\":
                        bs += 1
                        k -= 1
                    if bs % 2 == 0:
                        break
                i += 1
            continue
        if c == '"':
            parts, i = _string(src, i + 1)
            toks.append(Tok("str", parts, i))
            continue
        m = NUM_RE.match(src, i)
        if m and (c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit())):
            toks.append(Tok("num", m.group(), i))
            i = m.end()
            continue
        if c == ".":
            m = FIELD_RE.match(src, i)
            if m:
                toks.append(Tok("field", m.group()[1:], i))
                i = m.end()
                continue
        if c == "$":
            m = VAR_RE.match(src, i)
            if m:
                toks.append(Tok("var", m.group()[1:], i))
                i = m.end()
                continue
        if c == "@":
            m = FORMAT_RE.match(src, i)
            if m:
                toks.append(Tok("format", m.group(), i))
                i = m.end()
                continue
            raise JQSyntaxError("syntax error: unexpected '@'")
        if c.isalpha() or c == "_":
            m = IDENT_RE.match(src, i)
            w = m.group()
            toks.append(Tok("kw" if w in KEYWORDS else "ident", w, i))
            i = m.end()
            continue
        o = next((o for o in OPS3 + OPS2 if src.startswith(o, i)), None)
        if o:
            toks.append(Tok("op", o, i))
            i += len(o)
            continue
        if c in OPS1:
            if nested:
                if c == "(":
                    depth += 1
                elif c == ")":
                    if depth == 0:
                        return toks, i + 1
                    depth -= 1
            toks.append(Tok("op", c, i))
            i += 1
        else:
            raise JQSyntaxError("syntax error: unexpected INVALID_CHARACTER")
    if nested:
        raise JQSyntaxError("syntax error: unterminated string interpolation")
    toks.append(Tok("eof", None, n))
    return toks, i


def _string(src, i):
    """Lex a string body starting after the opening quote. Returns (parts, end)."""
    parts = []
    buf = []
    n = len(src)
    while True:
        if i >= n:
            raise JQSyntaxError("syntax error: unterminated string literal")
        c = src[i]
        if c == '"':
            i += 1
            break
        if c == "\\":
            i += 1
            if i >= n:
                raise JQSyntaxError("syntax error: unterminated string literal")
            e = src[i]
            if e in ESC:
                buf.append(ESC[e])
                i += 1
            elif e == "u":
                h = src[i + 1:i + 5]
                if len(h) < 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", h):
                    raise JQSyntaxError("syntax error: invalid \\u escape")
                cp = int(h, 16)
                i += 5
                if 0xD800 <= cp < 0xDC00 and src.startswith("\\u", i):
                    h2 = src[i + 2:i + 6]
                    if re.fullmatch(r"[dD][c-fC-F][0-9a-fA-F]{2}", h2):
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (int(h2, 16) - 0xDC00)
                        i += 6
                if 0xD800 <= cp < 0xE000:
                    cp = 0xFFFD
                buf.append(chr(cp))
            elif e == "(":
                if buf:
                    parts.append("".join(buf))
                    buf = []
                toks, i = tokenize(src, i + 1, nested=True)
                toks.append(Tok("eof", None, i))
                parts.append(toks)
            else:
                raise JQSyntaxError("syntax error: invalid escape '\\%s'" % e)
        else:
            buf.append(c)
            i += 1
    if buf or not parts:
        parts.append("".join(buf))
    return parts, i
