"""JSON values: type names, ordering, parsing and serialisation (jq semantics)."""
import decimal
import json
import math
import functools
from json.encoder import encode_basestring, encode_basestring_ascii


class JQError(Exception):
    """A jq runtime error carrying an arbitrary JSON value."""

    def __init__(self, value):
        Exception.__init__(self)
        self.value = value

    def message(self):
        v = self.value
        return v if isinstance(v, str) else tojson(v)


class NumLit(float):
    """A number parsed from a literal whose canonical text must be preserved."""
    __slots__ = ("lit",)

    def __new__(cls, f, lit):
        o = float.__new__(cls, f)
        o.lit = lit
        return o


MAXSAFE = 2 ** 53


def typename(v):
    if v is None:
        return "null"
    if v is True or v is False:
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


_ORDER = {"null": 0, "boolean": 2, "number": 3, "string": 4, "array": 5, "object": 6}


def _rank(v):
    if v is None:
        return 0
    if v is False:
        return 1
    if v is True:
        return 2
    if isinstance(v, (int, float)):
        return 3
    if isinstance(v, str):
        return 4
    if isinstance(v, list):
        return 5
    return 6


def _dec(x):
    if type(x) is NumLit:
        return decimal.Decimal(x.lit)
    return decimal.Decimal(x)


def _dec_cmp(a, b):
    try:
        da, db = _dec(a), _dec(b)
    except (decimal.InvalidOperation, ValueError):
        return 0
    return -1 if da < db else (1 if da > db else 0)


def compare(a, b):
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 3:
        if a != a:
            return -1
        if b != b:
            return 1
        if a == b and (type(a) is NumLit or type(b) is NumLit):
            return _dec_cmp(a, b)
        return -1 if a < b else (1 if a > b else 0)
    if ra == 4:
        return -1 if a < b else (1 if a > b else 0)
    if ra == 5:
        for x, y in zip(a, b):
            c = compare(x, y)
            if c:
                return c
        return (len(a) > len(b)) - (len(a) < len(b))
    if ra == 6:
        ka, kb = sorted(a), sorted(b)
        c = compare(ka, kb)
        if c:
            return c
        for k in ka:
            c = compare(a[k], b[k])
            if c:
                return c
        return 0
    return 0


sort_key = functools.cmp_to_key(compare)


def equals(a, b):
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return False
    if ra == 3:
        if a == b and (type(a) is NumLit or type(b) is NumLit):
            return _dec_cmp(a, b) == 0
        return a == b
    if ra < 3 or ra == 4:
        return True if ra < 3 else a == b
    if ra == 5:
        return len(a) == len(b) and all(equals(x, y) for x, y in zip(a, b))
    if len(a) != len(b):
        return False
    for k, v in a.items():
        if k not in b or not equals(v, b[k]):
            return False
    return True


def norm_num(x):
    """Normalise an arithmetic result: ints stay ints unless they exceed 2^53."""
    if isinstance(x, int):
        if -MAXSAFE <= x <= MAXSAFE:
            return x
        return float(x)
    return x


def truthy(v):
    return not (v is None or v is False)


# ---------------------------------------------------------------- numbers
def fmt_float(f):
    if f != f:
        return "null"
    if f in (math.inf, -math.inf):
        f = 1.7976931348623157e308 if f > 0 else -1.7976931348623157e308
    if f == 0:
        return "-0" if math.copysign(1, f) < 0 else "0"
    r = repr(abs(f))
    # decompose repr into digits and decimal point position
    if "e" in r:
        m, e = r.split("e")
        e = int(e)
    else:
        m, e = r, 0
    if "." in m:
        ip, fp = m.split(".")
    else:
        ip, fp = m, ""
    digits = ip + fp
    decpt = len(ip) + e
    stripped = digits.lstrip("0")
    decpt -= len(digits) - len(stripped)
    digits = stripped.rstrip("0") or "0"
    n = len(digits)
    sign = "-" if f < 0 else ""
    if decpt <= -4 or decpt > n + 15:
        ex = decpt - 1
        body = digits[0] + ("." + digits[1:] if n > 1 else "")
        return "%s%se%s%02d" % (sign, body, "-" if ex < 0 else "+", abs(ex))
    if decpt <= 0:
        return sign + "0." + "0" * (-decpt) + digits
    if decpt >= n:
        return sign + digits + "0" * (decpt - n)
    return sign + digits[:decpt] + "." + digits[decpt:]


def fmt_number(v):
    if isinstance(v, int):
        return str(v)
    if isinstance(v, NumLit):
        return v.lit
    return fmt_float(v)


# ---------------------------------------------------------------- serialise
def _esc(s, ascii_only=False):
    r = encode_basestring_ascii(s) if ascii_only else encode_basestring(s)
    if "\x7f" in r:
        r = r.replace("\x7f", "\\u007f")
    return r


DEFAULT_COLORS = ["0;90", "0;39", "0;39", "0;39", "0;32", "1;39", "1;39", "1;34"]


def tojson(v, sort_keys=False, ascii_only=False):
    out = []
    _dump(v, out, None, "", sort_keys, ascii_only, None)
    return "".join(out)


def dumps(v, indent=None, sort_keys=False, ascii_only=False, colors=None):
    """indent: None for compact, otherwise the indent string."""
    out = []
    _dump(v, out, indent, "", sort_keys, ascii_only, colors)
    return "".join(out)


def _dump(v, out, indent, cur, sk, asc, col):
    if v is None:
        out.append(col[0] + "null\x1b[0m" if col else "null")
    elif v is True:
        out.append(col[2] + "true\x1b[0m" if col else "true")
    elif v is False:
        out.append(col[1] + "false\x1b[0m" if col else "false")
    elif isinstance(v, (int, float)):
        s = fmt_number(v)
        out.append(col[3] + s + "\x1b[0m" if col else s)
    elif isinstance(v, str):
        s = _esc(v, asc)
        out.append(col[4] + s + "\x1b[0m" if col else s)
    elif isinstance(v, list):
        if not v:
            out.append(col[5] + "[]\x1b[0m" if col else "[]")
            return
        c = col[5] if col else ""
        nxt = cur + indent if indent is not None else cur
        out.append(c + "[")
        for i, x in enumerate(v):
            if i:
                out.append(c + "," if col else ",")
            if indent is not None:
                out.append("\n" + nxt)
            _dump(x, out, indent, nxt, sk, asc, col)
        if col:
            out.append(c)
        if indent is not None:
            out.append("\n" + cur)
        out.append(c + "]" + ("\x1b[0m" if col else ""))
    else:
        if not v:
            out.append(col[6] + "{}\x1b[0m" if col else "{}")
            return
        c = col[6] if col else ""
        R = "\x1b[0m" if col else ""
        kc = col[7] if col else ""
        nxt = cur + indent if indent is not None else cur
        out.append(c + "{")
        keys = sorted(v) if sk else list(v)
        for i, k in enumerate(keys):
            if i:
                out.append(c + ",")
            if indent is not None:
                out.append("\n" + nxt)
            out.append(R)
            if col:
                out.append(kc + _esc(k, asc) + R + c + ":" + R)
                if indent is not None:
                    out.append(" ")
            else:
                out.append(_esc(k, asc) + (": " if indent is not None else ":"))
            _dump(v[k], out, indent, nxt, sk, asc, col)
        out.append(c)
        if indent is not None:
            out.append("\n" + cur)
        out.append(c + "}" + R)


# ---------------------------------------------------------------- parse
def _pint(s):
    if s == "-0":
        return NumLit(-0.0, "-0")
    i = int(s)
    if -MAXSAFE <= i <= MAXSAFE:
        return i
    return NumLit(float(i), s)


def _pfloat(s):
    f = float(s)
    if f in (math.inf, -math.inf):
        return f
    if fmt_float(f) == s:
        return f
    try:
        return NumLit(f, str(decimal.Decimal(s)))
    except decimal.InvalidOperation:
        return f


def _pconst(s):
    if s == "NaN":
        return math.nan
    return math.inf if s == "Infinity" else -math.inf


_decoder = json.JSONDecoder(parse_int=_pint, parse_float=_pfloat,
                            parse_constant=_pconst, strict=False)
_WS = " \t\n\r﻿"


def _fix_surrogates(v):
    if isinstance(v, str):
        try:
            v.encode("utf-8")
            return v
        except UnicodeEncodeError:
            return "".join("�" if 0xD800 <= ord(c) <= 0xDFFF else c for c in v)
    if isinstance(v, list):
        return [_fix_surrogates(x) for x in v]
    if isinstance(v, dict):
        return {_fix_surrogates(k): _fix_surrogates(x) for k, x in v.items()}
    return v


class ParseError(Exception):
    pass


def _extra_literals(text, i):
    """Handle jq's non-standard literals nan / NaN / Infinity at position i."""
    for lit, val in (("nan", math.nan), ("-nan", math.nan), ("NaN", math.nan)):
        if text.startswith(lit, i):
            return val, i + len(lit)
    return None


def iter_values(text):
    """Yield (value, end_index) for each JSON text in `text`."""
    i, n = 0, len(text)
    while True:
        while i < n and text[i] in _WS:
            i += 1
        if i >= n:
            return
        try:
            v, j = _decoder.raw_decode(text, i)
        except json.JSONDecodeError as e:
            x = _extra_literals(text, i)
            if x is not None:
                v, j = x
            else:
                line = text.count("\n", 0, e.pos) + 1
                col = e.pos - (text.rfind("\n", 0, e.pos) + 1)
                msg = e.msg
                if e.pos >= n or msg.startswith("Expecting value") and e.pos >= n:
                    msg = "Unfinished JSON term at EOF"
                elif msg.startswith("Expecting value"):
                    msg = "Invalid literal"
                elif "Unterminated" in msg:
                    msg = "Unfinished string"
                elif msg.startswith("Expecting"):
                    msg = "Expected separator between values" if "delimiter" in msg else "Invalid numeric literal"
                raise ParseError("%s at line %d, column %d" % (msg, line, col))
        if j < n and text[j] not in _WS + '[]{},:"' and (
                isinstance(v, (int, float)) or v is None or isinstance(v, bool)):
            raise ParseError("Invalid numeric literal at line %d, column %d" % (
                text.count("\n", 0, j) + 1, j - (text.rfind("\n", 0, j) + 1) + 1))
        yield _fix_surrogates(v), j
        i = j


def parse_json(text):
    """Parse exactly one JSON text (used by fromjson / --argjson)."""
    vals = list(iter_values(text))
    if len(vals) != 1:
        raise ParseError("Unexpected extra JSON values" if vals else "Expected JSON value")
    return vals[0][0]
