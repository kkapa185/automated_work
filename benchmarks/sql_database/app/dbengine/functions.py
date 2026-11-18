"""Built-in scalar and aggregate functions."""
import math
import os
import re
import datetime
from decimal import Decimal, ROUND_HALF_UP
from .errors import SqlError
from .values import (to_text, to_numeric, typeof, format_real, cast_int, INT_MAX, INT_MIN, compare, truth,
                     bytes_to_text, num_prefix, sortkey, get_collation, add, mul)

SQLITE_VERSION = '3.45.0'


# ---------------------------------------------------------------- LIKE / GLOB
_like_cache = {}
_ASCII_LOWER = {i: i + 32 for i in range(65, 91)}


def _alower(s):
    return s.lower() if s.isascii() else s.translate(_ASCII_LOWER)


def like_regex(pat, esc):
    key = (pat, esc)
    r = _like_cache.get(key)
    if r is None:
        out = []
        i = 0
        n = len(pat)
        while i < n:
            c = pat[i]
            if esc is not None and c == esc and i + 1 < n:
                i += 1
                out.append(re.escape(_alower(pat[i])))
            elif c == '%':
                out.append('.*')
            elif c == '_':
                out.append('.')
            else:
                out.append(re.escape(_alower(c)))
            i += 1
        r = re.compile(''.join(out) + r'\Z', re.S)
        if len(_like_cache) > 500:
            _like_cache.clear()
        _like_cache[key] = r
    return r


def like(value, pattern, esc=None):
    if value is None or pattern is None:
        return None
    if esc is not None:
        esc = to_text(esc)
        if len(esc) != 1:
            raise SqlError('ESCAPE expression must be a single character')
    return 1 if like_regex(to_text(pattern), esc).match(_alower(to_text(value))) else 0


_glob_cache = {}


def glob_regex(pat):
    r = _glob_cache.get(pat)
    if r is None:
        out = []
        i = 0
        n = len(pat)
        while i < n:
            c = pat[i]
            if c == '*':
                out.append('.*')
            elif c == '?':
                out.append('.')
            elif c == '[':
                j = i + 1
                if j < n and pat[j] == '^':
                    j += 1
                if j < n and pat[j] == ']':
                    j += 1
                while j < n and pat[j] != ']':
                    j += 1
                if j >= n:
                    out.append(re.escape(c))
                else:
                    body = pat[i + 1:j]
                    neg = body.startswith('^')
                    if neg:
                        body = body[1:]
                    body = body.replace('\\', '\\\\').replace('[', '\\[')
                    out.append('[' + ('^' if neg else '') + body + ']')
                    i = j
            else:
                out.append(re.escape(c))
            i += 1
        r = re.compile(''.join(out) + r'\Z', re.S)
        if len(_glob_cache) > 500:
            _glob_cache.clear()
        _glob_cache[pat] = r
    return r


def glob(value, pattern):
    if value is None or pattern is None:
        return None
    return 1 if glob_regex(to_text(pattern)).match(to_text(value)) else 0


# ---------------------------------------------------------------- printf
_fmt_re = re.compile(r'%([-+ 0#,!]*)(\*|\d+)?(?:\.(\*|\d+))?(?:ll|l|h)?([a-zA-Z%])')


def _arg_int(v):
    if v is None:
        return 0
    v = to_numeric(v)
    return cast_int(v) if type(v) is float else v


def _arg_float(v):
    if v is None:
        return 0.0
    return float(to_numeric(v))


def sql_printf(fmt, args):
    fmt = to_text(fmt)
    out = []
    pos = 0
    ai = 0

    def nxt():
        nonlocal ai
        if ai < len(args):
            v = args[ai]
            ai += 1
            return v
        ai += 1
        return None

    for m in _fmt_re.finditer(fmt):
        out.append(fmt[pos:m.start()])
        pos = m.end()
        flags, width, prec, conv = m.groups()
        if conv == '%':
            out.append('%')
            continue
        if width == '*':
            w = _arg_int(nxt())
            if w < 0:
                flags += '-'
                w = -w
            width = str(w)
        if prec == '*':
            prec = str(max(_arg_int(nxt()), 0))
        w = int(width) if width else 0
        left = '-' in flags
        zero = '0' in flags and not left
        plus = '+' in flags
        space = ' ' in flags
        alt = '#' in flags
        if conv in 'di':
            v = _arg_int(nxt())
            s = str(abs(v))
            if prec is not None:
                s = s.rjust(int(prec), '0')
            sign = '-' if v < 0 else ('+' if plus else (' ' if space else ''))
            if zero and prec is None:
                s = s.rjust(w - len(sign), '0')
            s = sign + s
        elif conv == 'u':
            v = _arg_int(nxt())
            if v < 0:
                v += 1 << 64
            s = str(v)
        elif conv in 'xXo':
            v = _arg_int(nxt())
            if v < 0:
                v += 1 << 64
            s = format(v, conv if conv != 'o' else 'o')
            if prec is not None:
                s = s.rjust(int(prec), '0')
            if alt and v:
                s = ('0x' if conv == 'x' else '0X' if conv == 'X' else '0') + s
            if zero and prec is None:
                s = s.rjust(w, '0')
        elif conv in 'feEgG':
            v = _arg_float(nxt())
            if v != v:
                s = 'NaN'
            elif v in (float('inf'), float('-inf')):
                s = ('-' if v < 0 else ('+' if plus else '')) + 'Inf'
            else:
                p = int(prec) if prec is not None else 6
                f = '%' + ('#' if alt else '') + '.' + str(p) + conv
                s = f % abs(v)
                if '!' in flags and conv in 'gG' and '.' not in s and 'e' not in s.lower():
                    s += '.0'
                neg = v < 0 or (v == 0 and math.copysign(1, v) < 0 and False)
                sign = '-' if neg else ('+' if plus else (' ' if space else ''))
                if zero:
                    s = s.rjust(w - len(sign), '0')
                s = sign + s
        elif conv == 's' or conv == 'z':
            v = nxt()
            s = '' if v is None else to_text(v)
            if prec is not None:
                s = s[:int(prec)]
        elif conv == 'c':
            v = nxt()
            t = '' if v is None else to_text(v)
            s = t[:1]
        elif conv == 'q':
            v = nxt()
            s = '(NULL)' if v is None else to_text(v).replace("'", "''")
            if prec is not None:
                s = s[:int(prec)]
        elif conv == 'Q':
            v = nxt()
            s = 'NULL' if v is None else "'" + to_text(v).replace("'", "''") + "'"
        elif conv == 'w':
            v = nxt()
            s = '(NULL)' if v is None else to_text(v).replace('"', '""')
        elif conv == 'p':
            s = format(_arg_int(nxt()), 'x')
        else:
            out.append(m.group())
            continue
        if len(s) < w:
            s = s.ljust(w) if left else s.rjust(w)
        out.append(s)
    out.append(fmt[pos:])
    return ''.join(out)


# ---------------------------------------------------------------- scalar helpers
def f_abs(x):
    if x is None:
        return None
    if type(x) is int:
        if x == INT_MIN:
            raise SqlError('integer overflow')
        return abs(x)
    if type(x) is float:
        return abs(x)
    n = to_numeric(x)
    return abs(float(n)) if type(x) is not int else abs(n)


def f_length(x):
    if x is None:
        return None
    t = type(x)
    if t is bytes:
        return len(x)
    s = to_text(x)
    i = s.find('\0')
    return len(s) if i < 0 else i


def f_substr(s, y, z=None):
    if s is None or y is None or (z is None and False):
        return None
    isblob = type(s) is bytes
    if not isblob:
        s = to_text(s)
    y = _arg_int(y)
    n = len(s)
    if z is None:
        p2 = 1 << 40
        neg_p2 = False
    else:
        p2 = _arg_int(z)
        neg_p2 = p2 < 0
        if neg_p2:
            p2 = -p2
    p1 = y
    if p1 < 0:
        p1 += n
        if p1 < 0:
            p2 += p1
            if p2 < 0:
                p2 = 0
            p1 = 0
    elif p1 > 0:
        p1 -= 1
    elif p2 > 0:
        p2 -= 1
    if neg_p2:
        p1 -= p2
        if p1 < 0:
            p2 += p1
            p1 = 0
    if p1 > n:
        return b'' if isblob else ''
    return s[p1:p1 + p2]


def f_instr(x, y):
    if x is None or y is None:
        return None
    if type(x) is bytes and type(y) is bytes:
        return x.find(y) + 1
    return to_text(x).find(to_text(y)) + 1


def f_hex(x):
    if x is None:
        return ''
    if type(x) is not bytes:
        x = to_text(x).encode('utf-8')
    return x.hex().upper()


def f_unhex(x, ign=None):
    if x is None:
        return None
    s = to_text(x)
    if ign is not None:
        for c in to_text(ign):
            s = s.replace(c, '')
    if len(s) % 2 or not re.fullmatch(r'[0-9a-fA-F]*', s):
        return None
    return bytes.fromhex(s)


def f_quote(x):
    if x is None:
        return 'NULL'
    t = type(x)
    if t is int:
        return str(x)
    if t is float:
        s = format_real(x)
        return s
    if t is bytes:
        return "X'" + x.hex().upper() + "'"
    return "'" + x.replace("'", "''") + "'"


def f_replace(x, y, z):
    if x is None or y is None or z is None:
        return None
    x = to_text(x)
    y = to_text(y)
    if y == '':
        return x
    return x.replace(y, to_text(z))


def _trim_chars(chars):
    return ' ' if chars is None else to_text(chars)


def f_trim(x, chars=None):
    if x is None:
        return None
    return to_text(x).strip(_trim_chars(chars))


def f_ltrim(x, chars=None):
    if x is None:
        return None
    return to_text(x).lstrip(_trim_chars(chars))


def f_rtrim(x, chars=None):
    if x is None:
        return None
    return to_text(x).rstrip(_trim_chars(chars))


def f_round(x, n=None):
    if x is None:
        return None
    nd = 0 if n is None else _arg_int(n)
    nd = max(0, min(nd, 30))
    v = to_numeric(x)
    if type(x) is str and False:
        pass
    v = float(v)
    if v != v or v in (float('inf'), float('-inf')):
        return v
    if abs(v) >= 4.5e15:
        return v
    d = Decimal(repr(v)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)
    return float(d)


def f_sign(x):
    if x is None:
        return None
    if type(x) in (str, bytes):
        n, _ = num_prefix(to_text(x))
        if n is None:
            return None
        x = n
    return (x > 0) - (x < 0) if type(x) is int else float((x > 0) - (x < 0)) if False else (x > 0) - (x < 0)


def f_char(*args):
    out = []
    for a in args:
        if a is None:
            continue
        c = _arg_int(a)
        if c < 0 or c > 0x10FFFF or 0xD800 <= c <= 0xDFFF:
            c = 0xFFFD
        out.append(chr(c))
    return ''.join(out)


def f_unicode(x):
    if x is None:
        return None
    s = to_text(x)
    return ord(s[0]) if s else None


def f_upper(x):
    if x is None:
        return None
    s = to_text(x)
    return s.upper() if s.isascii() else ''.join(c.upper() if c.isascii() else c for c in s)


def f_lower(x):
    if x is None:
        return None
    s = to_text(x)
    return s.lower() if s.isascii() else ''.join(c.lower() if c.isascii() else c for c in s)


def f_zeroblob(n):
    if n is None:
        return None
    n = _arg_int(n)
    if n > 1000000000:
        raise SqlError('string or blob too big')
    return bytes(max(n, 0))


def f_randomblob(n):
    if n is None:
        return None
    return os.urandom(max(_arg_int(n), 1))


def f_random():
    return int.from_bytes(os.urandom(8), 'big', signed=True)


def f_typeof(x):
    return typeof(x)


def f_nullif(a, b):
    if a is None or b is None:
        return a
    from .values import compare as cmp
    return None if _equal(a, b) else a


def _equal(a, b):
    return compare(a, b) == 0


def f_likelihood(x, p):
    return x


def f_concat(*args):
    return ''.join(to_text(a) for a in args if a is not None)


def f_concat_ws(sep, *args):
    if sep is None:
        return None
    return to_text(sep).join(to_text(a) for a in args if a is not None)


def f_format(fmt, *args):
    if fmt is None:
        return None
    return sql_printf(fmt, args)


def _math1(fn):
    def f(x):
        if x is None:
            return None
        try:
            r = fn(float(to_numeric(x)))
        except (ValueError, OverflowError):
            return None
        return r
    return f


def f_pow(x, y):
    if x is None or y is None:
        return None
    try:
        return math.pow(float(to_numeric(x)), float(to_numeric(y)))
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def f_mod(x, y):
    if x is None or y is None:
        return None
    x = float(to_numeric(x))
    y = float(to_numeric(y))
    if y == 0:
        return None
    return math.fmod(x, y)


def f_log(*args):
    try:
        if len(args) == 1:
            if args[0] is None:
                return None
            return math.log10(float(to_numeric(args[0])))
        if args[0] is None or args[1] is None:
            return None
        return math.log(float(to_numeric(args[1]))) / math.log(float(to_numeric(args[0])))
    except (ValueError, ZeroDivisionError):
        return None


def f_ceil(x):
    if x is None:
        return None
    v = to_numeric(x)
    if type(v) is int:
        return v
    return float(math.ceil(v)) if math.isfinite(v) else v


def f_floor(x):
    if x is None:
        return None
    v = to_numeric(x)
    if type(v) is int:
        return v
    return float(math.floor(v)) if math.isfinite(v) else v


def f_trunc(x):
    if x is None:
        return None
    v = to_numeric(x)
    if type(v) is int:
        return v
    return float(math.trunc(v)) if math.isfinite(v) else v


# ---------------------------------------------------------------- date & time
_JD_EPOCH = datetime.datetime(1970, 1, 1)


def _to_dt(v, mods=()):
    if v is None:
        return None
    mods = list(mods)
    unix = any(m is not None and to_text(m).strip().lower() == 'unixepoch' for m in mods)
    if type(v) in (int, float):
        try:
            if unix:
                dt = _JD_EPOCH + datetime.timedelta(seconds=float(v))
            else:
                dt = _JD_EPOCH + datetime.timedelta(days=float(v) - 2440587.5)
        except OverflowError:
            return None
    else:
        s = to_text(v).strip()
        if s.lower() == 'now':
            dt = datetime.datetime.utcnow()
        else:
            dt = None
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M', '%Y-%m-%d', '%H:%M:%S',
                        '%H:%M'):
                try:
                    dt = datetime.datetime.strptime(s, fmt)
                    if fmt.startswith('%H'):
                        dt = dt.replace(year=2000, month=1, day=1)
                    break
                except ValueError:
                    continue
            if dt is None:
                n, end = num_prefix(s)
                if n is not None and end == len(s):
                    dt = _JD_EPOCH + datetime.timedelta(days=float(n) - 2440587.5)
                else:
                    return None
    for m in mods:
        if m is None:
            return None
        m = to_text(m).strip().lower()
        mm = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*(second|minute|hour|day|month|year)s?', m)
        if mm:
            n = float(mm.group(1))
            u = mm.group(2)
            if u == 'month' or u == 'year':
                months = int(n) * (12 if u == 'year' else 1)
                y = dt.year + (dt.month - 1 + months) // 12
                mo = (dt.month - 1 + months) % 12 + 1
                import calendar
                day = dt.day
                last = calendar.monthrange(y, mo)[1]
                extra = 0
                if day > last:
                    extra = day - last
                    day = last
                dt = dt.replace(year=y, month=mo, day=day) + datetime.timedelta(days=extra)
            else:
                dt += datetime.timedelta(**{u + 's': n})
        elif m == 'start of day':
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif m == 'start of month':
            dt = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif m == 'start of year':
            dt = dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        elif m in ('unixepoch', 'utc', 'localtime', 'auto'):
            pass
        else:
            return None
    return dt


def _safe(fn):
    def g(*a):
        try:
            return fn(*a)
        except (OverflowError, ValueError):
            return None
    return g


def f_date(v='now', *mods):
    dt = _to_dt(v, mods)
    return None if dt is None else dt.strftime('%Y-%m-%d')


def f_time(v='now', *mods):
    dt = _to_dt(v, mods)
    return None if dt is None else dt.strftime('%H:%M:%S')


def f_datetime(v='now', *mods):
    dt = _to_dt(v, mods)
    return None if dt is None else dt.strftime('%Y-%m-%d %H:%M:%S')


def f_julianday(v='now', *mods):
    dt = _to_dt(v, mods)
    if dt is None:
        return None
    return (dt - _JD_EPOCH).total_seconds() / 86400.0 + 2440587.5


def f_unixepoch(v='now', *mods):
    dt = _to_dt(v, mods)
    if dt is None:
        return None
    return int((dt - _JD_EPOCH).total_seconds())


def f_strftime(fmt, v='now', *mods):
    if fmt is None:
        return None
    dt = _to_dt(v, mods)
    if dt is None:
        return None
    out = []
    f = to_text(fmt)
    i = 0
    while i < len(f):
        c = f[i]
        if c == '%' and i + 1 < len(f):
            i += 1
            d = f[i]
            if d == 'Y':
                out.append('%04d' % dt.year)
            elif d == 'm':
                out.append('%02d' % dt.month)
            elif d == 'd':
                out.append('%02d' % dt.day)
            elif d == 'H':
                out.append('%02d' % dt.hour)
            elif d == 'M':
                out.append('%02d' % dt.minute)
            elif d == 'S':
                out.append('%02d' % dt.second)
            elif d == 's':
                out.append(str(int((dt - _JD_EPOCH).total_seconds())))
            elif d == 'f':
                out.append('%06.3f' % (dt.second + dt.microsecond / 1e6))
            elif d == 'j':
                out.append('%03d' % dt.timetuple().tm_yday)
            elif d == 'J':
                out.append(format_real((dt - _JD_EPOCH).total_seconds() / 86400.0 + 2440587.5))
            elif d == 'w':
                out.append(str((dt.weekday() + 1) % 7))
            elif d == 'W':
                out.append('%02d' % int(dt.strftime('%W')))
            elif d == '%':
                out.append('%')
            else:
                out.append('%' + d)
        else:
            out.append(c)
        i += 1
    return ''.join(out)


# ---------------------------------------------------------------- function table
# name -> (min_args, max_args (-1 = variadic), callable)
SCALARS = {
    'abs': (1, 1, f_abs), 'char': (0, -1, f_char), 'hex': (1, 1, f_hex), 'unhex': (1, 2, f_unhex),
    'instr': (2, 2, f_instr), 'length': (1, 1, f_length), 'lower': (1, 1, f_lower), 'upper': (1, 1, f_upper),
    'ltrim': (1, 2, f_ltrim), 'rtrim': (1, 2, f_rtrim), 'trim': (1, 2, f_trim), 'nullif': (2, 2, f_nullif),
    'quote': (1, 1, f_quote), 'replace': (3, 3, f_replace), 'round': (1, 2, f_round), 'sign': (1, 1, f_sign),
    'substr': (2, 3, f_substr), 'substring': (2, 3, f_substr), 'typeof': (1, 1, f_typeof),
    'unicode': (1, 1, f_unicode), 'random': (0, 0, f_random), 'randomblob': (1, 1, f_randomblob),
    'zeroblob': (1, 1, f_zeroblob), 'likelihood': (2, 2, f_likelihood), 'likely': (1, 1, lambda x: x),
    'unlikely': (1, 1, lambda x: x), 'concat': (1, -1, f_concat), 'concat_ws': (2, -1, f_concat_ws),
    'format': (1, -1, f_format), 'printf': (1, -1, f_format), 'glob': (2, 2, lambda p, v: glob(v, p)),
    'like': (2, 3, lambda p, v, e=None: like(v, p, e)),
    'sqlite_version': (0, 0, lambda: SQLITE_VERSION), 'sqlite_source_id': (0, 0, lambda: 'db1000'),
    'date': (0, -1, _safe(f_date)), 'time': (0, -1, _safe(f_time)), 'datetime': (0, -1, _safe(f_datetime)),
    'julianday': (0, -1, _safe(f_julianday)), 'unixepoch': (0, -1, _safe(f_unixepoch)), 'strftime': (1, -1, _safe(f_strftime)),
    'ceil': (1, 1, f_ceil), 'ceiling': (1, 1, f_ceil), 'floor': (1, 1, f_floor), 'trunc': (1, 1, f_trunc),
    'sqrt': (1, 1, _math1(math.sqrt)), 'exp': (1, 1, _math1(math.exp)), 'ln': (1, 1, _math1(math.log)),
    'log10': (1, 1, _math1(math.log10)), 'log2': (1, 1, _math1(math.log2)), 'log': (1, 2, f_log),
    'power': (2, 2, f_pow), 'pow': (2, 2, f_pow), 'mod': (2, 2, f_mod), 'pi': (0, 0, lambda: math.pi),
    'sin': (1, 1, _math1(math.sin)), 'cos': (1, 1, _math1(math.cos)), 'tan': (1, 1, _math1(math.tan)),
    'asin': (1, 1, _math1(math.asin)), 'acos': (1, 1, _math1(math.acos)), 'atan': (1, 1, _math1(math.atan)),
    'atan2': (2, 2, lambda y, x: None if y is None or x is None else math.atan2(float(to_numeric(y)), float(to_numeric(x)))),
    'degrees': (1, 1, _math1(math.degrees)), 'radians': (1, 1, _math1(math.radians)),
    'sinh': (1, 1, _math1(math.sinh)), 'cosh': (1, 1, _math1(math.cosh)), 'tanh': (1, 1, _math1(math.tanh)),
}

# functions needing lazy/short-circuit evaluation or db access are compiled specially in compiler.py
SPECIAL = {'coalesce': (2, -1), 'ifnull': (2, 2), 'iif': (3, 3), 'if': (3, 3), 'max': (2, -1), 'min': (2, -1),
           'last_insert_rowid': (0, 0), 'changes': (0, 0), 'total_changes': (0, 0)}


# ---------------------------------------------------------------- aggregates
class AggCount:
    def __init__(self, ck=None):
        self.n = 0

    def step(self, v):
        if v is not None:
            self.n += 1

    def final(self):
        return self.n


class AggCountStar:
    def __init__(self, ck=None):
        self.n = 0

    def step(self, v=None):
        self.n += 1

    def final(self):
        return self.n


class AggSum:
    total_mode = False

    def __init__(self, ck=None):
        self.i = 0
        self.f = 0.0
        self.isf = False
        self.any = False

    def step(self, v):
        if v is None:
            return
        self.any = True
        t = type(v)
        if t is int:
            n = v
        elif t is float:
            n = v
        else:
            n = to_numeric(v)
            if t is bytes or t is str:
                # non-numeric text counts as 0 (integer if looks integral)
                pass
        if type(n) is float:
            if not self.isf:
                self.isf = True
                self.f = float(self.i)
            self.f += n
        elif self.isf:
            self.f += n
        else:
            self.i += n
            if not INT_MIN <= self.i <= INT_MAX:
                if self.total_mode:
                    self.isf = True
                    self.f = float(self.i)
                else:
                    raise SqlError('integer overflow')

    def final(self):
        if not self.any:
            return 0.0 if self.total_mode else None
        if self.total_mode:
            return self.f if self.isf else float(self.i)
        return self.f if self.isf else self.i


class AggTotal(AggSum):
    total_mode = True


class AggAvg:
    def __init__(self, ck=None):
        self.s = AggTotal()
        self.n = 0

    def step(self, v):
        if v is None:
            return
        self.n += 1
        self.s.step(v)

    def final(self):
        if self.n == 0:
            return None
        return self.s.final() / self.n


class AggMinMax:
    def __init__(self, ck=None, is_max=False):
        self.ck = ck
        self.best = None
        self.is_max = is_max
        self.have = False

    def step(self, v):
        if v is None:
            return False
        if not self.have:
            self.best = v
            self.have = True
            return True
        c = compare(v, self.best, self.ck)
        if (c > 0 and self.is_max) or (c < 0 and not self.is_max):
            self.best = v
            return True
        return False

    def final(self):
        return self.best


class AggMin(AggMinMax):
    def __init__(self, ck=None):
        AggMinMax.__init__(self, ck, False)


class AggMax(AggMinMax):
    def __init__(self, ck=None):
        AggMinMax.__init__(self, ck, True)


class AggGroupConcat:
    def __init__(self, ck=None):
        self.parts = []

    def step(self, v, sep=None):
        if v is None:
            return
        if self.parts:
            self.parts.append(',' if sep is None else to_text(sep))
        self.parts.append(to_text(v))

    def final(self):
        if not self.parts:
            return None
        return ''.join(self.parts)


AGGREGATES = {
    'count': AggCount, 'sum': AggSum, 'total': AggTotal, 'avg': AggAvg, 'min': AggMin, 'max': AggMax,
    'group_concat': AggGroupConcat, 'string_agg': AggGroupConcat,
}
