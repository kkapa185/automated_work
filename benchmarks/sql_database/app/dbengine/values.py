"""Storage classes, affinity, comparison, collation, arithmetic and formatting.

Values are Python None (NULL), int (INTEGER), float (REAL), str (TEXT), bytes (BLOB).
"""
import re
from .errors import SqlError

INT_MIN = -(1 << 63)
INT_MAX = (1 << 63) - 1
WS = ' \t\n\f\r'

_num_re = re.compile(r'[ \t\n\f\r]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)')
_int_re = re.compile(r'[ \t\n\f\r]*([+-]?\d+)')


def typeof(v):
    if v is None:
        return 'null'
    t = type(v)
    if t is int:
        return 'integer'
    if t is float:
        return 'real'
    if t is str:
        return 'text'
    return 'blob'


def format_real(f):
    if f != f:
        return 'NaN'
    if f == float('inf'):
        return 'Inf'
    if f == float('-inf'):
        return '-Inf'
    s = '%.15g' % f
    if float(s) != f and f.is_integer():
        s = '%.17g' % f
    if 'e' in s:
        m, e = s.split('e')
        if '.' not in m:
            m += '.0'
        return m + 'e' + e
    if '.' not in s:
        s += '.0'
    return s


def bytes_to_text(b):
    return b.decode('utf-8', 'replace')


def to_text(v):
    if v is None:
        return None
    t = type(v)
    if t is str:
        return v
    if t is int:
        return str(v)
    if t is float:
        return format_real(v)
    return bytes_to_text(v)


def num_prefix(s):
    """Parse the longest numeric prefix of s. Returns (value, end) or (None, 0)."""
    m = _num_re.match(s)
    if not m:
        return None, 0
    t = m.group(1)
    if '.' in t or 'e' in t or 'E' in t:
        return float(t), m.end()
    v = int(t)
    if v < INT_MIN or v > INT_MAX:
        return float(t), m.end()
    return v, m.end()


def text_numeric_whole(s):
    """Number if the whole string (modulo surrounding blanks) is numeric, else None."""
    v, end = num_prefix(s)
    if v is None:
        return None
    if s[end:].strip(WS) == '':
        return v
    return None


def to_numeric(v):
    t = type(v)
    if t is int or t is float:
        return v
    if t is bytes:
        v = bytes_to_text(v)
    n, _ = num_prefix(v)
    return 0 if n is None else n


def truth(v):
    """SQL truth value: True / False / None."""
    if v is None:
        return None
    t = type(v)
    if t is int:
        return v != 0
    if t is float:
        return v != 0.0
    return to_numeric(v) != 0


def type_affinity(decl):
    d = (decl or '').upper()
    if 'INT' in d:
        return 'INTEGER'
    if 'CHAR' in d or 'CLOB' in d or 'TEXT' in d:
        return 'TEXT'
    if 'BLOB' in d or d.strip() == '':
        return 'BLOB'
    if 'REAL' in d or 'FLOA' in d or 'DOUB' in d:
        return 'REAL'
    return 'NUMERIC'


def apply_affinity(v, aff):
    if v is None or aff == 'BLOB' or aff is None:
        return v
    t = type(v)
    if aff == 'TEXT':
        if t is int or t is float:
            return to_text(v)
        return v
    if t is str:
        n = text_numeric_whole(v)
        if n is None:
            return v
        v = n
        t = type(n)
    elif t is bytes:
        return v
    if aff == 'REAL':
        if t is int:
            return float(v)
        return v
    if t is float and v.is_integer() and -9.2233720368547758e18 <= v < 9.2233720368547758e18:
        return int(v)
    return v


# ---------------------------------------------------------------- collations
_ASCII_LOWER = {i: i + 32 for i in range(65, 91)}


def _nocase(s):
    if s.isascii():
        return s.lower()
    return s.translate(_ASCII_LOWER)


def _rtrim(s):
    return s.rstrip(' ')


COLLATIONS = {'BINARY': None, 'NOCASE': _nocase, 'RTRIM': _rtrim}


def get_collation(name):
    n = name.upper()
    if n not in COLLATIONS:
        raise SqlError('no such collation sequence: %s' % name, 'parse')
    return COLLATIONS[n]


def compare(a, b, ck=None):
    """Three-way comparison of two non-NULL values (affinity already applied)."""
    ta = type(a)
    tb = type(b)
    if ta is int or ta is float:
        if tb is int or tb is float:
            return -1 if a < b else (1 if a > b else 0)
        return -1
    if ta is str:
        if tb is str:
            if ck:
                a = ck(a)
                b = ck(b)
            return -1 if a < b else (1 if a > b else 0)
        if tb is bytes:
            return -1
        return 1
    if tb is bytes:
        return -1 if a < b else (1 if a > b else 0)
    return 1


def sortkey(v, ck=None):
    if v is None:
        return (0, 0)
    t = type(v)
    if t is int or t is float:
        return (1, v)
    if t is str:
        return (2, ck(v) if ck else v)
    return (3, v)


def row_sortkey(row):
    return tuple([sortkey(v) for v in row])


# ---------------------------------------------------------------- cast
def _clamp(i):
    return INT_MAX if i > INT_MAX else (INT_MIN if i < INT_MIN else i)


def cast_int(v):
    t = type(v)
    if t is int:
        return v
    if t is float:
        if v != v:
            return 0
        if v >= 9.2233720368547758e18:
            return INT_MAX
        if v <= -9.2233720368547758e18:
            return INT_MIN
        return int(v)
    if t is bytes:
        v = bytes_to_text(v)
    m = _int_re.match(v)
    if not m:
        return 0
    return _clamp(int(m.group(1)))


def cast_real(v):
    t = type(v)
    if t is float:
        return v
    if t is int:
        return float(v)
    if t is bytes:
        v = bytes_to_text(v)
    n, _ = num_prefix(v)
    return 0.0 if n is None else float(n)


def cast_numeric(v):
    t = type(v)
    if t is int or t is float:
        return apply_affinity(v, 'NUMERIC')
    if t is bytes:
        v = bytes_to_text(v)
    n, _ = num_prefix(v)
    if n is None:
        return 0
    return apply_affinity(n, 'NUMERIC')


def cast_value(v, typename):
    if v is None:
        return None
    aff = type_affinity(typename)
    if aff == 'INTEGER':
        return cast_int(v)
    if aff == 'REAL':
        return cast_real(v)
    if aff == 'TEXT':
        return to_text(v)
    if aff == 'BLOB':
        if type(v) is bytes:
            return v
        return to_text(v).encode('utf-8')
    return cast_numeric(v)


# ---------------------------------------------------------------- arithmetic
def _int_result(r, a, b, op):
    if INT_MIN <= r <= INT_MAX:
        return r
    return op(float(a), float(b))


def add(a, b):
    if a is None or b is None:
        return None
    if type(a) is not int:
        a = to_numeric(a)
    if type(b) is not int:
        b = to_numeric(b)
    r = a + b
    if type(r) is int and not INT_MIN <= r <= INT_MAX:
        r = float(a) + float(b)
    return None if r != r else r


def sub(a, b):
    if a is None or b is None:
        return None
    if type(a) is not int:
        a = to_numeric(a)
    if type(b) is not int:
        b = to_numeric(b)
    r = a - b
    if type(r) is int and not INT_MIN <= r <= INT_MAX:
        r = float(a) - float(b)
    return None if r != r else r


def mul(a, b):
    if a is None or b is None:
        return None
    if type(a) is not int:
        a = to_numeric(a)
    if type(b) is not int:
        b = to_numeric(b)
    try:
        r = a * b
    except OverflowError:
        r = float(a) * float(b)
    if type(r) is int and not INT_MIN <= r <= INT_MAX:
        r = float(a) * float(b)
    return None if r != r else r


def div(a, b):
    if a is None or b is None:
        return None
    a = to_numeric(a)
    b = to_numeric(b)
    if b == 0:
        return None
    if type(a) is int and type(b) is int:
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            q = -q
        if q > INT_MAX:
            return float(q)
        return q
    r = a / b
    return None if r != r else r


def mod(a, b):
    if a is None or b is None:
        return None
    a = to_numeric(a)
    b = to_numeric(b)
    isf = type(a) is float or type(b) is float
    if isf:
        a = cast_int(a)
        b = cast_int(b)
    if b == 0:
        return None
    r = abs(a) % abs(b)
    if a < 0:
        r = -r
    return float(r) if isf else r


def _wrap64(x):
    x &= (1 << 64) - 1
    return x - (1 << 64) if x >= (1 << 63) else x


def _int_operand(v):
    v = to_numeric(v)
    return cast_int(v) if type(v) is float else v


def bit_and(a, b):
    if a is None or b is None:
        return None
    return _int_operand(a) & _int_operand(b)


def bit_or(a, b):
    if a is None or b is None:
        return None
    return _int_operand(a) | _int_operand(b)


def shift_left(a, b):
    if a is None or b is None:
        return None
    a = _int_operand(a)
    b = _int_operand(b)
    if b < 0:
        return shift_right(a, -b if b != INT_MIN else INT_MAX)
    if b >= 64:
        return 0
    return _wrap64(a << b)


def shift_right(a, b):
    if a is None or b is None:
        return None
    a = _int_operand(a)
    b = _int_operand(b)
    if b < 0:
        return shift_left(a, -b if b != INT_MIN else INT_MAX)
    if b >= 64:
        return -1 if a < 0 else 0
    return a >> b


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


def neg(a):
    if a is None:
        return None
    a = to_numeric(a)
    if type(a) is int:
        r = -a
        return r if r <= INT_MAX else float(r)
    return -a


def bitnot(a):
    if a is None:
        return None
    return ~_int_operand(a)
