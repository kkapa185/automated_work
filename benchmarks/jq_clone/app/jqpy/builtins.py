"""Builtin functions: natives, special forms and the jq-defined prelude."""
import math
import os
import sys
import itertools
from .values import (JQError, NumLit, typename, compare, equals, truthy, tojson, sort_key,
                     parse_json, ParseError, norm_num, fmt_number)
from .lexer import JQSyntaxError
from . import interp
from .interp import (NOPATH, np, isnum, err, dump_trunc, index_value, getpath, setpath, delpaths,
                     op_add, op_sub, Closure, Scope, make_call, norm_float, invalid_path,
                     iterate, split_str, indices_of, HaltEx, Env)
from . import formats, regexfn, dates
from .parser import parse, parse_number


class State(object):
    """Runtime state shared with the CLI (inputs, stderr, filename...)."""
    next_input = None
    filename = None
    stderr = sys.stderr
    lib_dirs = []


STATE = State()

PRELUDE = r'''
def values: select(. != null);
def nulls: select(. == null);
def booleans: select(type == "boolean");
def numbers: select(type == "number");
def strings: select(type == "string");
def arrays: select(type == "array");
def objects: select(type == "object");
def iterables: select(type == "array" or type == "object");
def scalars: select(type != "array" and type != "object");
def normals: select(isnormal);
def map(f): [.[] | f];
def map_values(f): .[] |= f;
def recurse(f; cond): recurse(f | select(cond));
def recurse_down: recurse;
def del(f): delpaths([path(f)]);
def paths: path(..) | select(length > 0);
def paths(node_filter): . as $dot | paths | select(. as $p | $dot | getpath($p) | node_filter);
def leaf_paths: paths(scalars);
def pick(pathexps): . as $top | reduce path(pathexps) as $p (null; setpath($p; $top | getpath($p)));
def with_entries(f): to_entries | map(f) | from_entries;
def walk(f): def w: if type == "object" then map_values(w) elif type == "array" then map(w) else . end | f; w;
def in(xs): . as $x | xs | has($x);
def inside(xs): . as $x | xs | contains($x);
def combinations: if length == 0 then [] else .[0][] as $x | (.[1:] | combinations) as $w | [$x] + $w end;
def combinations(n): . as $dot | [range(n)] | map($dot) | combinations;
def transpose: if . == [] then [] else . as $in | (map(length) | max) as $max | [range(0; $max) as $j | [range(0; $in | length) as $i | $in[$i][$j]]] end;
def first: .[0];
def last: .[-1];
def nth($n): .[$n];
def abs: if . < 0 then - . else . end;
def toarray: if type == "array" then . else [.] end;
def splits($re): splits($re; null);
def splits($re; flags): split($re; flags) | .[];
def todate: todateiso8601;
def fromdate: fromdateiso8601;
def date: todate;
def dateadd(u; n): . + n;
def datesub(u; n): . - n;
def tostream: path(def r: (.[]? | r), .; r) as $p | getpath($p) | reduce path(.[]?) as $q ([$p, .]; [$p + $q]);
def fromstream(f): {x: null, e: false} as $init
  | foreach f as $i ($init;
      if .e then $init else . end
      | if $i | length == 2
        then setpath(["e"]; $i[0] | length == 0) | setpath(["x"] + $i[0]; $i[1])
        else setpath(["e"]; $i[0] | length == 1) end;
      if .e then .x else empty end);
def truncate_stream(stream): . as $n | null | stream | . as $input | if (.[0] | length) > $n then setpath([0]; .[0][$n:]) else empty end;
def INDEX(stream; idx_expr): reduce stream as $row ({}; .[$row | idx_expr | tostring] |= $row);
def INDEX(idx_expr): INDEX(.[]; idx_expr);
def JOIN($idx; idx_expr): [.[] | [., $idx[idx_expr]]];
def JOIN($idx; stream; idx_expr): stream | [., $idx[idx_expr]];
def JOIN($idx; stream; idx_expr; join_expr): stream | [., $idx[idx_expr]] | join_expr;
def IN(s): any(s == .; .);
def IN(src; s): any(src == s; .);
def ascii: if type == "number" and . >= 0 and . <= 127 then [.] | implode else error("ascii only takes numbers between 0 and 127") end;
def debug(msg): (msg | debug | empty), .;
def halt_error: halt_error(5);
def capture(re): capture(re; null);
def scan(re): scan(re; null);
def test(re): test(re; null);
def match(re): match(re; null);
def sub(re; str): sub(re; str; "");
def gsub(re; str): sub(re; str; "g");
def gsub(re; str; flags): sub(re; str; flags + "g");
def add(f): reduce f as $x (null; . + $x);
def add: add(.[]);
def any: any(.[]; .);
def any(f): any(.[]; f);
def all: all(.[]; .);
def all(f): all(.[]; f);
def input_line_number: 0;
def get_search_list: [];
'''


# ------------------------------------------------------------------ natives
def need_num(v, what=None):
    if not isnum(v):
        raise err("%s (%s) number required" % (typename(v), dump_trunc(v)))
    return v


def tostring(v):
    return v if isinstance(v, str) else tojson(v)


def n_length(v):
    if v is None:
        return 0
    if v is True or v is False:
        raise err("boolean (%s) has no length" % tojson(v))
    if isnum(v):
        return norm_float(abs(v)) if not isinstance(v, NumLit) else (v if v >= 0 else norm_float(-v))
    return len(v)


def n_utf8bytelength(v):
    if not isinstance(v, str):
        raise err("%s (%s) only strings have UTF-8 byte length" % (typename(v), dump_trunc(v)))
    return len(v.encode("utf-8", "surrogatepass"))


def n_keys(v):
    if isinstance(v, dict):
        return sorted(v)
    if isinstance(v, list):
        return list(range(len(v)))
    raise err("%s (%s) has no keys" % (typename(v), dump_trunc(v)))


def n_keys_unsorted(v):
    if isinstance(v, dict):
        return list(v)
    return n_keys(v)


def n_has(v, k):
    if isinstance(v, dict) and isinstance(k, str):
        return k in v
    if isinstance(v, list) and isnum(k):
        return 0 <= k < len(v)
    raise err("Cannot check whether %s has a %s key" % (typename(v), typename(k)))


def _contains(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return all(k in a and _contains(a[k], bv) for k, bv in b.items())
    if isinstance(a, list) and isinstance(b, list):
        return all(any(_contains(x, y) for x in a) for y in b)
    if isinstance(a, str) and isinstance(b, str):
        return b in a
    return equals(a, b)


def contains(a, b):
    if typename(a) == typename(b):
        return _contains(a, b)
    raise err("%s (%s) and %s (%s) cannot have their containment checked" % (
        typename(a), dump_trunc(a), typename(b), dump_trunc(b)))


def n_tonumber(v):
    if isnum(v):
        return v
    if isinstance(v, str):
        import re
        if re.fullmatch(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", v):
            try:
                return parse_number(v.lstrip("-")) if False else _neg_wrap(v)
            except ValueError:
                pass
        if v in ("nan", "-nan"):
            return math.nan
        raise err("Cannot parse '%s' as number" % v if False else "%s (%s) cannot be parsed as a number" % (
            typename(v), dump_trunc(v)))
    raise err("%s (%s) cannot be parsed as a number" % (typename(v), dump_trunc(v)))


def _neg_wrap(s):
    neg = s.startswith("-")
    x = parse_number(s[1:] if neg else s)
    if neg:
        if isinstance(x, int):
            return -x if x else NumLit(-0.0, "-0")
        return NumLit(-float(x), "-" + x.lit) if isinstance(x, NumLit) else -x
    return x


def n_toboolean(v):
    if v is True or v is False:
        return v
    if v == "true":
        return True
    if v == "false":
        return False
    raise err("%s (%s) cannot be parsed as a boolean" % (typename(v), dump_trunc(v)))


def n_type(v):
    return typename(v)


def n_sort(v):
    if not isinstance(v, list):
        raise err("%s (%s) cannot be sorted, as it is not an array" % (typename(v), dump_trunc(v)))
    return sorted(v, key=sort_key)


def n_unique(v):
    s = n_sort(v)
    out = []
    for x in s:
        if not out or not equals(out[-1], x):
            out.append(x)
    return out


def n_min(v):
    if not isinstance(v, list):
        raise err("%s (%s) cannot be iterated over" % (typename(v), dump_trunc(v)))
    best = None
    for i, x in enumerate(v):
        if i == 0 or compare(x, best) < 0:
            best = x
    return best


def n_max(v):
    if not isinstance(v, list):
        raise err("%s (%s) cannot be iterated over" % (typename(v), dump_trunc(v)))
    best = None
    for i, x in enumerate(v):
        if i == 0 or compare(x, best) >= 0:
            best = x
    return best


def n_reverse(v):
    if v is None:
        return []
    if isinstance(v, str):
        return v[::-1]
    if isinstance(v, list):
        return v[::-1]
    raise err("Cannot reverse %s (%s)" % (typename(v), dump_trunc(v)) if False else
              "Cannot index %s with number" % typename(v))


def n_indices(v, x):
    if v is None:
        return None
    if isinstance(v, str):
        if not isinstance(x, str):
            raise err("Cannot determine indices of %s in string" % typename(x) if False else
                      "Cannot index string with %s" % typename(x))
        if x == "":
            return None
        out = []
        i = v.find(x)
        while i >= 0:
            out.append(i)
            i = v.find(x, i + 1)
        return out
    if isinstance(v, list):
        if isinstance(x, list):
            return indices_of(v, x)
        return indices_of(v, x)
    raise err("Cannot index %s with %s" % (typename(v), typename(x)))


def n_index(v, x):
    r = n_indices(v, x)
    return r[0] if r else None


def n_rindex(v, x):
    r = n_indices(v, x)
    return r[-1] if r else None


def n_startswith(v, x):
    if not isinstance(v, str) or not isinstance(x, str):
        raise err("startswith() requires string inputs")
    return v.startswith(x)


def n_endswith(v, x):
    if not isinstance(v, str) or not isinstance(x, str):
        raise err("endswith() requires string inputs")
    return v.endswith(x)


def n_ltrimstr(v, x):
    if isinstance(v, str) and isinstance(x, str) and v.startswith(x):
        return v[len(x):]
    return v


def n_rtrimstr(v, x):
    if isinstance(v, str) and isinstance(x, str) and x and v.endswith(x):
        return v[:-len(x)]
    return v


def n_trimstr(v, x):
    return n_rtrimstr(n_ltrimstr(v, x), x)


def _trim(v, l, r):
    if not isinstance(v, str):
        raise err("%s (%s) cannot be trimmed" % (typename(v), dump_trunc(v)))
    if l and r:
        return v.strip()
    return v.lstrip() if l else v.rstrip()


def n_explode(v):
    if not isinstance(v, str):
        raise err("%s (%s) cannot be exploded" % (typename(v), dump_trunc(v)))
    return [ord(c) for c in v]


def n_implode(v):
    if not isinstance(v, list):
        raise err("%s (%s) cannot be imploded" % (typename(v), dump_trunc(v)) if False else
                  "Cannot iterate over %s" % typename(v) if False else "implode input must be an array")
    out = []
    for c in v:
        if not isnum(c):
            raise err("Unicode codepoint must be numeric" if False else "Unicode codepoint must be numeric")
        c = int(c)
        if c > 0x10FFFF or 0xD800 <= c < 0xE000 or c < 0:
            raise err("Invalid codepoint literal")
        out.append(chr(c))
    return "".join(out)


def n_split1(v, sep):
    if not isinstance(v, str) or not isinstance(sep, str):
        raise err("split input and separator must be strings")
    return split_str(v, sep)


def n_join(v, sep):
    if not isinstance(v, list) and not isinstance(v, dict):
        raise err("Cannot iterate over %s%s" % (typename(v), "" if v is None else " (%s)" % dump_trunc(v)))
    items = list(v.values()) if isinstance(v, dict) else v
    if not items:
        return ""
    parts = []
    for x in items:
        if x is None:
            parts.append("")
        elif isinstance(x, str):
            parts.append(x)
        elif isinstance(x, (bool, int, float)):
            parts.append(tojson(x))
        else:
            raise err("%s (%s) and %s (%s) cannot be added" % ("string", dump_trunc(tojson_join(parts, sep)),
                                                               typename(x), dump_trunc(x)))
    if len(items) > 1 and not isinstance(sep, str):
        if sep is None:
            return "".join(parts)
        raise err("%s (%s) and %s (%s) cannot be added" % ("string", dump_trunc(parts[0]),
                                                           typename(sep), dump_trunc(sep)))
    return sep.join(parts) if isinstance(sep, str) else parts[0]


def tojson_join(parts, sep):
    return (sep if isinstance(sep, str) else "").join(parts)


def n_ascii_upcase(v):
    if not isinstance(v, str):
        raise err("ascii_upcase input must be a string")
    return "".join(chr(ord(c) - 32) if "a" <= c <= "z" else c for c in v)


def n_ascii_downcase(v):
    if not isinstance(v, str):
        raise err("ascii_downcase input must be a string")
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in v)


def n_fromjson(v):
    if not isinstance(v, str):
        raise err("%s (%s) cannot be parsed as JSON" % (typename(v), dump_trunc(v)) if False else
                  "%s (%s) only strings can be parsed" % (typename(v), dump_trunc(v)))
    try:
        return parse_json(v)
    except ParseError as e:
        raise err("%s (while parsing '%s')" % (e, v))


def n_flatten(v, depth=None):
    if depth is None:
        depth = 1e9
    if not isnum(depth):
        raise err("flatten depth must not be negative" if False else "flatten depth must be a number")
    if depth < 0:
        raise err("flatten depth must not be negative")
    if not isinstance(v, (list, dict)):
        raise err("Cannot iterate over %s%s" % (typename(v), "" if v is None else " (%s)" % dump_trunc(v)))

    def fl(a, d):
        out = []
        for x in (a.values() if isinstance(a, dict) else a):
            if isinstance(x, list) and d > 0:
                out.extend(fl(x, d - 1))
            else:
                out.append(x)
        return out
    return fl(v, depth)


def n_to_entries(v):
    if isinstance(v, dict):
        return [{"key": k, "value": x} for k, x in v.items()]
    if isinstance(v, list):
        return [{"key": i, "value": x} for i, x in enumerate(v)] if False else \
            (_ for _ in ()).throw(err("Cannot index array with string \"key\"")) if False else \
            [{"key": i, "value": x} for i, x in enumerate(v)]
    raise err("%s (%s) has no keys" % (typename(v), dump_trunc(v)))


def n_from_entries(v):
    if not isinstance(v, (list, dict)):
        raise err("Cannot iterate over %s%s" % (typename(v), "" if v is None else " (%s)" % dump_trunc(v)))
    out = {}
    for x in (v if isinstance(v, list) else v.values()):
        if not isinstance(x, dict):
            raise err("Cannot index %s with \"key\"" % typename(x))
        k = None
        for name in ("key", "k", "name", "Name", "K", "Key"):
            if x.get(name) is not None:
                k = x[name]
                break
        if not isinstance(k, str):
            k = tojson(k)
        for name in ("value", "v", "Value", "V"):
            if name in x:
                val = x[name]
                break
        else:
            val = None
        out[k] = val
    return out


def n_tojson(v):
    return tojson(v)


def n_setpath(v, p, x):
    if not isinstance(p, list):
        raise err("Path must be specified as an array")
    return setpath(v, p, x)


def n_delpaths(v, ps):
    return delpaths(v, ps)


def n_bsearch(v, x):
    if not isinstance(v, list):
        raise err("%s (%s) cannot be searched from" % (typename(v), dump_trunc(v)))
    lo, hi = 0, len(v) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        c = compare(v[mid], x)
        if c == 0:
            return mid
        if c < 0:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1 - lo


def n_infinite(v):
    return math.inf


def n_nan(v):
    return math.nan


def n_isinfinite(v):
    need_num(v)
    return v in (math.inf, -math.inf)


def n_isnan(v):
    need_num(v)
    return v != v


def n_isnormal(v):
    need_num(v)
    return v == v and v not in (math.inf, -math.inf) and v != 0 and abs(v) >= 2.2250738585072014e-308


def n_not(v):
    return not truthy(v)


def n_tostring(v):
    return tostring(v)


def n_env(v):
    return dict(os.environ)


def n_now(v):
    import time
    return time.time()


def n_builtins(v):
    return sorted("%s/%d" % k for k in BUILTINS.all_keys() if not k[0].startswith("_"))


def n_input_filename(v):
    return STATE.filename


def n_halt(v):
    raise HaltEx(0)


def n_halt_error(v, code):
    if not isnum(code):
        raise err("halt_error/1: number required")
    raise HaltEx(int(code), v)


def n_error0(v):
    raise JQError(v)


def n_error1(v, m):
    raise JQError(m)


# ---- math
def _wrap1(fn):
    def g(v):
        need_num(v)
        try:
            r = fn(v)
        except ValueError:
            return math.nan
        except OverflowError:
            return math.inf
        return norm_float(r) if isinstance(r, float) else r
    return g


def _log(fn, neg_inf_at_zero=True):
    def g(x):
        if x == 0:
            return -math.inf
        if x < 0:
            return math.nan
        if x == math.inf:
            return math.inf
        return fn(x)
    return g


def _round_half_away(x):
    if x != x or x in (math.inf, -math.inf):
        return x
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def _floor(x):
    if x != x or x in (math.inf, -math.inf):
        return x
    return math.floor(x)


def _ceil(x):
    if x != x or x in (math.inf, -math.inf):
        return x
    return math.ceil(x)


def _trunc(x):
    if x != x or x in (math.inf, -math.inf):
        return x
    return math.trunc(x)


def _rint(x):
    if x != x or x in (math.inf, -math.inf):
        return x
    return round(x)


def _significand(x):
    if x == 0 or x != x or x in (math.inf, -math.inf):
        return x
    m, e = math.frexp(x)
    return m * 2


def _logb(x):
    if x == 0:
        return -math.inf
    if x in (math.inf, -math.inf):
        return math.inf
    if x != x:
        return x
    return math.frexp(x)[1] - 1


def _gamma(x):
    if x <= 0 and x == math.floor(x):
        return math.inf
    return math.lgamma(x)


def _tgamma(x):
    if x == 0:
        return math.copysign(math.inf, x)
    if x < 0 and x == math.floor(x):
        return math.nan
    try:
        return math.gamma(x)
    except OverflowError:
        return math.inf


def _cbrt(x):
    if x != x or x in (math.inf, -math.inf) or x == 0:
        return x
    r = math.copysign(abs(x) ** (1.0 / 3), x)
    rr = round(r)
    return float(rr) if rr ** 3 == x else r


def _exp(fn):
    def g(x):
        try:
            return fn(x)
        except OverflowError:
            return math.inf
    return g


def _unavail(name):
    def g(v, *a):
        raise err("%s is not available" % name)
    return g


MATH1 = {
    "floor": _floor, "ceil": _ceil, "round": _round_half_away, "trunc": _trunc, "rint": _rint,
    "nearbyint": _rint, "sqrt": lambda x: math.sqrt(x) if x >= 0 else math.nan if x == x else x,
    "fabs": abs, "exp": _exp(math.exp), "exp2": _exp(lambda x: 2.0 ** x),
    "exp10": _exp(lambda x: 10.0 ** x), "expm1": _exp(math.expm1),
    "log": _log(math.log), "log2": _log(math.log2), "log10": _log(math.log10),
    "log1p": lambda x: -math.inf if x == -1 else (math.nan if x < -1 else math.log1p(x)),
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
    "atan": math.atan, "sinh": _exp(math.sinh), "cosh": _exp(math.cosh), "tanh": math.tanh,
    "asinh": math.asinh, "acosh": math.acosh, "atanh": lambda x: math.copysign(math.inf, x) if abs(x) == 1 else math.atanh(x),
    "cbrt": lambda x: _cbrt(x),
    "significand": _significand, "logb": _logb, "gamma": _gamma, "lgamma": _gamma,
    "tgamma": _tgamma, "erf": math.erf, "erfc": math.erfc,
    "j0": _unavail("j0"), "j1": _unavail("j1"), "y0": _unavail("y0"), "y1": _unavail("y1"),
}


def _pow(a, b):
    try:
        return math.pow(a, b)
    except ZeroDivisionError:
        return math.inf
    except OverflowError:
        return math.inf
    except ValueError:
        return math.nan


def _drem(a, b):
    try:
        return math.remainder(a, b)
    except ValueError:
        return math.nan


def _fmod(a, b):
    try:
        return math.fmod(a, b)
    except ValueError:
        return math.nan


def _ldexp(a, b):
    try:
        return math.ldexp(a, int(b))
    except OverflowError:
        return math.inf


MATH2 = {
    "pow": _pow, "atan2": math.atan2, "fmod": _fmod, "hypot": math.hypot,
    "copysign": math.copysign, "drem": _drem, "remainder": _drem, "ldexp": _ldexp,
    "scalb": lambda a, b: _ldexp(a, b) if b == int(b) else a * (2.0 ** b),
    "scalbln": _ldexp, "nextafter": math.nextafter, "nexttoward": math.nextafter,
    "fmin": lambda a, b: b if a != a else (a if b != b else min(a, b)),
    "fmax": lambda a, b: b if a != a else (a if b != b else max(a, b)),
    "fdim": lambda a, b: a - b if a > b else 0.0,
    "jn": _unavail("jn"), "yn": _unavail("yn"),
}


def _math1(name, fn):
    def g(v):
        need_num(v)
        try:
            r = fn(v)
        except ValueError:
            return math.nan
        except OverflowError:
            return math.inf
        except ZeroDivisionError:
            return math.inf
        return norm_float(r) if isinstance(r, float) else r
    return g


def _math2(fn):
    def g(v, a, b):
        need_num(a)
        need_num(b)
        try:
            r = fn(a, b)
        except (ValueError, OverflowError, ZeroDivisionError):
            return math.nan
        return norm_float(r) if isinstance(r, float) else r
    return g


def n_frexp(v):
    need_num(v)
    if v != v or v in (math.inf, -math.inf):
        return [v, 0]
    m, e = math.frexp(v)
    return [norm_float(m), e]


def n_modf(v):
    need_num(v)
    if v in (math.inf, -math.inf):
        return [math.copysign(0.0, v), v]
    f, i = math.modf(v)
    return [norm_float(f), norm_float(i)]


def n_lgamma_r(v):
    need_num(v)
    g = _gamma(v)
    sign = -1 if (v < 0 and math.floor(v) % 2 != 0 and v != math.floor(v)) else 1
    return [norm_float(g), sign]


def n_fma(v, a, b, c):
    return norm_float(need_num(a) * need_num(b) + need_num(c))


def n_trim(v):
    return _trim(v, True, True)


def n_ltrim(v):
    return _trim(v, True, False)


def n_rtrim(v):
    return _trim(v, False, True)


def n_test2(v, r, f):
    return regexfn.do_test(v, r, f)


def n_split2(v, r, f):
    return regexfn.do_split(v, r, f)


def n_gmtime(v):
    return dates.gmtime(v)


def n_localtime(v):
    return dates.localtime(v)


def n_mktime(v):
    return dates.mktime(v)


def n_strftime(v, f):
    return dates.strftime(v, f)


def n_strflocaltime(v, f):
    return dates.strftime(v, f, "strflocaltime/1", True)


def n_strptime(v, f):
    return dates.strptime(v, f)


def n_todateiso(v):
    return dates.todateiso8601(v)


def n_fromdateiso(v):
    return dates.fromdateiso8601(v)


def n_have_literal(v):
    return True


def n_have_decnum(v):
    return True


def n_stderr(v):
    STATE.stderr.write(v if isinstance(v, str) else tojson(v))
    STATE.stderr.flush()
    return v


def n_debug(v):
    STATE.stderr.write(tojson(["DEBUG:", v]) + "\n")
    STATE.stderr.flush()
    return v


def n_input(v):
    try:
        return STATE.next_input()
    except StopIteration:
        raise err("No more inputs")


def n_modulemeta(v):
    if not isinstance(v, str):
        raise err("modulemeta input module name must be a string")
    from .modules import module_meta
    return module_meta(v, STATE)


NATIVES = {
    ("length", 0): n_length, ("utf8bytelength", 0): n_utf8bytelength, ("not", 0): n_not,
    ("keys", 0): n_keys, ("keys_unsorted", 0): n_keys_unsorted, ("has", 1): n_has,
    ("contains", 1): contains, ("tostring", 0): n_tostring, ("tonumber", 0): n_tonumber,
    ("toboolean", 0): n_toboolean, ("type", 0): n_type, ("sort", 0): n_sort,
    ("unique", 0): n_unique, ("min", 0): n_min, ("max", 0): n_max, ("reverse", 0): n_reverse,
    ("indices", 1): n_indices, ("_indices", 1): n_indices, ("index", 1): n_index,
    ("rindex", 1): n_rindex, ("startswith", 1): n_startswith, ("endswith", 1): n_endswith,
    ("ltrimstr", 1): n_ltrimstr, ("rtrimstr", 1): n_rtrimstr, ("trimstr", 1): n_trimstr,
    ("trim", 0): n_trim, ("ltrim", 0): n_ltrim, ("rtrim", 0): n_rtrim,
    ("explode", 0): n_explode, ("implode", 0): n_implode, ("split", 1): n_split1,
    ("split", 2): n_split2, ("join", 1): n_join, ("ascii_upcase", 0): n_ascii_upcase,
    ("ascii_downcase", 0): n_ascii_downcase, ("tojson", 0): n_tojson, ("fromjson", 0): n_fromjson,
    ("flatten", 0): n_flatten, ("flatten", 1): n_flatten,
    ("to_entries", 0): n_to_entries, ("from_entries", 0): n_from_entries,
    ("setpath", 2): n_setpath, ("delpaths", 1): n_delpaths, ("bsearch", 1): n_bsearch,
    ("infinite", 0): n_infinite, ("nan", 0): n_nan, ("isinfinite", 0): n_isinfinite,
    ("isnan", 0): n_isnan, ("isnormal", 0): n_isnormal,
    ("isfinite", 0): lambda v: (need_num(v), v == v and v not in (math.inf, -math.inf))[1],
    ("env", 0): n_env, ("now", 0): n_now, ("builtins", 0): n_builtins,
    ("input_filename", 0): n_input_filename, ("halt", 0): n_halt, ("halt_error", 1): n_halt_error,
    ("error", 0): n_error0, ("error", 1): n_error1,
    ("frexp", 0): n_frexp, ("modf", 0): n_modf, ("lgamma_r", 0): n_lgamma_r, ("fma", 3): n_fma,
    ("test", 2): n_test2, ("gmtime", 0): n_gmtime, ("localtime", 0): n_localtime,
    ("mktime", 0): n_mktime, ("strftime", 1): n_strftime, ("strflocaltime", 1): n_strflocaltime,
    ("strptime", 1): n_strptime, ("todateiso8601", 0): n_todateiso,
    ("fromdateiso8601", 0): n_fromdateiso,
    ("have_literal_numbers", 0): n_have_literal, ("have_decnum", 0): n_have_decnum,
    ("stderr", 0): n_stderr, ("debug", 0): n_debug, ("input", 0): n_input,
    ("modulemeta", 0): n_modulemeta,
    ("tojson", 0): n_tojson,
}
for _n, _f in MATH1.items():
    NATIVES[(_n, 0)] = _math1(_n, _f)
for _n, _f in MATH2.items():
    NATIVES[(_n, 2)] = _math2(_f)


# generator natives: value -> iterable of values
def g_match(v, r, f):
    return regexfn.do_match(v, r, f)


def g_capture(v, r, f):
    return [regexfn.capture_obj(m) for m in regexfn.do_match(v, r, f)]


def g_scan(v, r, f):
    out = []
    ff = "g" + f if isinstance(f, str) else "g"
    for m in regexfn.do_match(v, r, ff):
        if m["captures"]:
            out.append([c["string"] for c in m["captures"]])
        else:
            out.append(m["string"])
    return out


GENERATORS = {
    ("match", 2): g_match, ("capture", 2): g_capture, ("scan", 2): g_scan,
}


def input_or_stop_gen():
    while True:
        try:
            yield STATE.next_input()
        except StopIteration:
            return


# ------------------------------------------------------------------ special forms
def _cartesian(argfns, env, v, i=0):
    if i == len(argfns):
        yield ()
        return
    for _, a in argfns[i](env, None, v):
        for rest in _cartesian(argfns, env, v, i + 1):
            yield (a,) + rest


def mk_native(fn, argfns):
    n = len(argfns)
    if n == 0:
        def f0(env, p, v):
            yield (None if p is None else NOPATH), fn(v)
        return f0
    if n == 1:
        a0 = argfns[0]

        def f1(env, p, v):
            for _, a in a0(env, None, v):
                yield (None if p is None else NOPATH), fn(v, a)
        return f1

    def fn_(env, p, v):
        for args in _cartesian(argfns, env, v):
            yield (None if p is None else NOPATH), fn(v, *args)
    return fn_


def mk_generator(fn, argfns):
    def f(env, p, v):
        for args in _cartesian(argfns, env, v):
            for x in fn(v, *args):
                yield (None if p is None else NOPATH), x
    return f


def sp_empty(c, a):
    def f(env, p, v):
        return iter(())
    return f


def sp_select(c, a):
    cond = a[0]

    def f(env, p, v):
        for _, x in cond(env, None, v):
            if truthy(x):
                yield p, v
    return f


def sp_path(c, a):
    body = a[0]

    def f(env, p, v):
        for pp, pv in body(env, (), v):
            if pp is NOPATH:
                raise invalid_path(pv)
            yield (None if p is None else NOPATH), list(pp)
    return f


def sp_getpath(c, a):
    arg = a[0]

    def f(env, p, v):
        for _, pth in arg(env, None, v):
            if not isinstance(pth, list):
                raise err("Path must be specified as an array")
            try:
                r = getpath(v, pth)
            except JQError:
                if p is None:
                    raise
                r = None
            if p is None:
                yield None, r
            else:
                yield p + tuple(pth), r
    return f


def sp_recurse0(c, a):
    def f(env, p, v):
        yield p, v
        stack = [_children(p, v)]
        while stack:
            try:
                cp, cv = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            yield cp, cv
            stack.append(_children(cp, cv))
    return f


def _children(p, v):
    if isinstance(v, list):
        for i, x in enumerate(v):
            yield (None if p is None else p + (i,)), x
    elif isinstance(v, dict):
        for k, x in v.items():
            yield (None if p is None else p + (k,)), x


def sp_recurse1(c, a):
    body = a[0]

    def f(env, p, v):
        yield p, v
        stack = [body(env, p, v)]
        while stack:
            try:
                cp, cv = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            yield cp, cv
            stack.append(body(env, cp, cv))
    return f


def sp_range(c, a):
    def f(env, p, v):
        for args in _cartesian(a, env, v):
            if len(args) == 1:
                lo, hi, by = 0, args[0], 1
            elif len(args) == 2:
                lo, hi, by = args[0], args[1], 1
            else:
                lo, hi, by = args
            for x in (lo, hi, by):
                if not isnum(x):
                    raise err("Range bounds must be numeric")
            if by > 0:
                x = lo
                while x < hi:
                    yield (None if p is None else NOPATH), x
                    x = op_add(x, by)
            elif by < 0:
                x = lo
                while x > hi:
                    yield (None if p is None else NOPATH), x
                    x = op_add(x, by)
            elif lo < hi:
                while True:
                    yield (None if p is None else NOPATH), lo
    return f


def sp_first(c, a):
    body = a[0]

    def f(env, p, v):
        for item in body(env, p, v):
            yield item
            return
    return f


def sp_last(c, a):
    body = a[0]

    def f(env, p, v):
        got = False
        last = None
        for item in body(env, p, v):
            got = True
            last = item
        if got:
            yield last
    return f


def sp_nth(c, a):
    nf, body = a

    def f(env, p, v):
        for _, n in nf(env, None, v):
            if not isnum(n):
                raise err("Invalid nth index" if False else "Cannot index with non-number")
            if n < 0:
                raise err("Out of bounds negative array index")
            i = 0
            for item in body(env, p, v):
                if i >= n:
                    yield item
                    break
                i += 1
    return f


def sp_skip(c, a):
    nf, body = a

    def f(env, p, v):
        for _, n in nf(env, None, v):
            if not isnum(n):
                raise err("Invalid skip count")
            if n < 0:
                raise err("Invalid negative skip count" if False else "Out of bounds negative array index")
            i = 0
            for item in body(env, p, v):
                if i >= n:
                    yield item
                i += 1
    return f


def sp_isempty(c, a):
    body = a[0]

    def f(env, p, v):
        for _ in body(env, None, v):
            yield np(p), False
            return
        yield np(p), True
    return f


def sp_until(c, a):
    cond, upd = a

    def f(env, p, v):
        stack = [iter([(p, v)])]
        while stack:
            try:
                cp, cv = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            nxt = []
            for _, cc in cond(env, None, cv):
                if truthy(cc):
                    yield cp, cv
                else:
                    nxt.append((cp, cv))
            for it in reversed(nxt):
                stack.append(upd(env, it[0], it[1]))
    return f


def sp_while(c, a):
    cond, upd = a

    def f(env, p, v):
        stack = [iter([(p, v)])]
        while stack:
            try:
                cp, cv = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            for _, cc in cond(env, None, cv):
                if truthy(cc):
                    yield cp, cv
                    stack.append(upd(env, cp, cv))
    return f


_DONE = object()


def sp_repeat(c, a):
    """repeat(f): f | (., repeat(f)).  The next sibling output of f is fetched
    (so errors surface) before descending into the output just emitted."""
    body = a[0]

    def f(env, p, v):
        stack = [[body(env, p, v), _DONE]]
        while stack:
            fr = stack[-1]
            if fr[1] is not _DONE:
                item, fr[1] = fr[1], _DONE
            else:
                try:
                    item = next(fr[0])
                except StopIteration:
                    stack.pop()
                    continue
            yield item
            try:
                fr[1] = next(fr[0])
            except StopIteration:
                fr[1] = _DONE
            stack.append([body(env, item[0], item[1]), _DONE])
    return f


def sp_any(c, a):
    gen, cond = a

    def f(env, p, v):
        for _, x in gen(env, None, v):
            for _, y in cond(env, None, x):
                if truthy(y):
                    yield np(p), True
                    return
        yield np(p), False
    return f


def sp_all(c, a):
    gen, cond = a

    def f(env, p, v):
        for _, x in gen(env, None, v):
            for _, y in cond(env, None, x):
                if not truthy(y):
                    yield np(p), False
                    return
        yield np(p), True
    return f


def _keyed(a):
    kf = a[0]

    def keys_of(env, v):
        if not isinstance(v, list):
            raise err("Cannot index %s with number" % typename(v) if not isinstance(v, dict) else
                      "Cannot index object with number")
        return [[y for _, y in kf(env, None, x)] for x in v]
    return keys_of


def sp_sort_by(c, a):
    ko = _keyed(a)

    def f(env, p, v):
        ks = ko(env, v)
        idx = sorted(range(len(v)), key=lambda i: sort_key(ks[i]))
        yield np(p), [v[i] for i in idx]
    return f


def sp_group_by(c, a):
    ko = _keyed(a)

    def f(env, p, v):
        ks = ko(env, v)
        idx = sorted(range(len(v)), key=lambda i: sort_key(ks[i]))
        out = []
        last = None
        for i in idx:
            if out and equals(last, ks[i]):
                out[-1].append(v[i])
            else:
                out.append([v[i]])
                last = ks[i]
        yield np(p), out
    return f


def sp_unique_by(c, a):
    ko = _keyed(a)

    def f(env, p, v):
        ks = ko(env, v)
        idx = sorted(range(len(v)), key=lambda i: sort_key(ks[i]))
        out = []
        last = None
        for i in idx:
            if out and equals(last, ks[i]):
                continue
            out.append(v[i])
            last = ks[i]
        yield np(p), out
    return f


def sp_min_by(c, a):
    ko = _keyed(a)

    def f(env, p, v):
        ks = ko(env, v)
        best = None
        for i in range(len(v)):
            if best is None or compare(ks[i], ks[best]) < 0:
                best = i
        yield np(p), (v[best] if best is not None else None)
    return f


def sp_max_by(c, a):
    ko = _keyed(a)

    def f(env, p, v):
        ks = ko(env, v)
        best = None
        for i in range(len(v)):
            if best is None or compare(ks[i], ks[best]) >= 0:
                best = i
        yield np(p), (v[best] if best is not None else None)
    return f


def sp_sub(c, a):
    refn, replfn, flagfn = a

    def f(env, p, v):
        for _, rv in refn(env, None, v):
            for _, fl in flagfn(env, None, v):
                if not isinstance(v, str):
                    raise err("%s (%s) cannot be matched, as it is not a string" % (typename(v), dump_trunc(v)))
                rx, fl2 = regexfn.split_args(rv, fl)
                ms = regexfn.do_match(v, rx, fl2)

                def build(i, prefix, prev):
                    if i == len(ms):
                        yield prefix + v[prev:]
                        return
                    m = ms[i]
                    gap = v[prev:m["offset"]]
                    for _, r in replfn(env, None, regexfn.capture_obj(m)):
                        if not isinstance(r, str):
                            raise err("%s (%s) cannot be added to a string" % (typename(r), dump_trunc(r)))
                        yield from build(i + 1, prefix + gap + r, m["offset"] + m["length"])
                for s in build(0, "", 0):
                    yield np(p), s
    return f


def sp_inputs(c, a):
    def f(env, p, v):
        while True:
            try:
                x = STATE.next_input()
            except StopIteration:
                return
            yield np(p), x
    return f


def sp_limit(c, a):
    nf, body = a

    def f(env, p, v):
        for _, n in nf(env, None, v):
            if not isnum(n):
                raise err("Invalid limit")
            if n < 0:
                raise err("Invalid negative limit" if False else "Invalid limit")
            if n == 0:
                continue
            i = 0
            for item in body(env, p, v):
                yield item
                i += 1
                if i >= n:
                    break
    return f


SPECIALS = {
    ("empty", 0): sp_empty, ("select", 1): sp_select, ("path", 1): sp_path,
    ("getpath", 1): sp_getpath, ("recurse", 0): sp_recurse0, ("recurse", 1): sp_recurse1,
    ("range", 1): sp_range, ("range", 2): sp_range, ("range", 3): sp_range,
    ("first", 1): sp_first, ("last", 1): sp_last, ("nth", 2): sp_nth, ("skip", 2): sp_skip,
    ("isempty", 1): sp_isempty, ("until", 2): sp_until, ("while", 2): sp_while,
    ("repeat", 1): sp_repeat, ("any", 2): sp_any, ("all", 2): sp_all,
    ("sort_by", 1): sp_sort_by, ("group_by", 1): sp_group_by, ("unique_by", 1): sp_unique_by,
    ("min_by", 1): sp_min_by, ("max_by", 1): sp_max_by, ("limit", 2): sp_limit,
    ("inputs", 0): sp_inputs,
}


class Builtins(object):
    def __init__(self):
        self.defs = {}
        self._parsed = False
        self.closures = {}

    def _load(self):
        if self._parsed:
            return
        self._parsed = True
        _, _, body = parse(PRELUDE)
        node = body
        while node[0] == "funcdef":
            _, name, params, fbody, rest = node
            self.defs[(name, len(params))] = (params, fbody)
            node = rest

    def all_keys(self):
        self._load()
        keys = set(NATIVES) | set(SPECIALS) | set(GENERATORS) | set(self.defs)
        keys |= {("sub", 2), ("sub", 3)}
        return keys

    def formatter(self, name):
        return formats.get_format(name)

    def resolve(self, comp, name, args, sc):
        self._load()
        key = (name, len(args))
        if key == ("sub", 3):
            fns = [comp.compile(a, sc) for a in args]
            return sp_sub(comp, fns)
        if key in self.defs:
            clo = self.closure(key, comp)
            argfns = [comp.compile(a, sc) for a in args]
            return make_call(lambda env: clo, argfns)
        argfns = [comp.compile(a, sc) for a in args]
        if key in SPECIALS:
            return SPECIALS[key](comp, argfns)
        if key in NATIVES:
            return mk_native(NATIVES[key], argfns)
        if key in GENERATORS:
            return mk_generator(GENERATORS[key], argfns)
        raise JQSyntaxError("%s/%d is not defined" % key)

    def closure(self, key, comp):
        c = self.closures.get(key)
        if c is None:
            params, body = self.defs[key]
            bsc = None
            for prm in params:
                if prm.startswith("$"):
                    bsc = Scope("v", prm[1:], 0, bsc)
                    bsc = Scope("f", prm[1:], 0, bsc)
                else:
                    bsc = Scope("f", prm, 0, bsc)
            c = Closure(tuple(params), None, None)
            self.closures[key] = c
            c.body = comp.compile(body, bsc)
        return c


BUILTINS = Builtins()
