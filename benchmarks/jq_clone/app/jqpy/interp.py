"""Compiler from AST to Python generator closures, plus core jq semantics."""
import math
from .values import (JQError, NumLit, typename, compare, equals, truthy, tojson, norm_num,
                     fmt_number)
from .lexer import JQSyntaxError


class NoPath(object):
    def __repr__(self):
        return "NOPATH"


NOPATH = NoPath()


class BreakEx(Exception):
    def __init__(self, token):
        Exception.__init__(self)
        self.token = token


class HaltEx(Exception):
    def __init__(self, code, msg=None):
        Exception.__init__(self)
        self.code = code
        self.msg = msg


def dump_trunc(v, limit=11):
    s = tojson(v)
    b = s.encode("utf-8", "replace")
    if len(b) > 10 + 3 + 1 - 1 and len(b) > 14:
        s = b[:11].decode("utf-8", "ignore") + "..."
    return s


def err(msg):
    return JQError(msg)


def isnum(x):
    t = type(x)
    return t is int or t is float or t is NumLit


# ------------------------------------------------------------ core operations
def _slice_bounds(n, lo, hi):
    def conv(x, default, is_end):
        if x is None:
            return default
        if not isnum(x):
            raise err("Start and end indices of an array slice must be numbers")
        if x != x:
            return default
        if x in (math.inf, -math.inf):
            x = n if x > 0 else -n - 1
        x = math.ceil(x) if is_end else math.floor(x)
        x = int(x)
        if x < 0:
            x += n
        return max(0, min(n, x))
    a = conv(lo, 0, False)
    b = conv(hi, n, True)
    if b < a:
        b = a
    return a, b


def index_value(v, k):
    if isinstance(v, dict):
        if isinstance(k, str):
            return v.get(k)
    elif isinstance(v, list):
        if isnum(k):
            if k != k:
                return None
            i = math.floor(k)
            if i < 0:
                i += len(v)
            return v[i] if 0 <= i < len(v) else None
        if isinstance(k, dict):
            a, b = _slice_bounds(len(v), k.get("start"), k.get("end"))
            return v[a:b]
        if isinstance(k, list):
            return indices_of(v, k)
    elif v is None:
        if isinstance(k, str) or isnum(k) or k is None:
            return None
        if isinstance(k, dict):
            return None
    elif isinstance(v, str):
        if isinstance(k, dict):
            a, b = _slice_bounds(len(v), k.get("start"), k.get("end"))
            return v[a:b]
    if isinstance(k, str):
        raise err('Cannot index %s with "%s"' % (typename(v), k))
    raise err("Cannot index %s with %s" % (typename(v), typename(k)))


def indices_of(v, k):
    if isinstance(v, list) and isinstance(k, list):
        if not k:
            return None
        n, m = len(v), len(k)
        return [i for i in range(n - m + 1) if all(equals(v[i + j], k[j]) for j in range(m))]
    if isinstance(v, list):
        return [i for i, x in enumerate(v) if equals(x, k)]
    return []


def iterate(v):
    if isinstance(v, list):
        return enumerate(v)
    if isinstance(v, dict):
        return v.items()
    raise err("Cannot iterate over %s%s" % (typename(v), "" if v is None else " (%s)" % dump_trunc(v)))


def getpath(v, path):
    for k in path:
        if v is None:
            return None
        v = index_value(v, k)
    return v


def setpath(v, path, nv, i=0):
    if i == len(path):
        return nv
    k = path[i]
    if isinstance(k, str):
        if v is None:
            return {k: setpath(None, path, nv, i + 1)}
        if not isinstance(v, dict):
            raise err('Cannot index %s with "%s"' % (typename(v), k))
        r = dict(v)
        r[k] = setpath(v.get(k), path, nv, i + 1)
        return r
    if isnum(k):
        if v is None:
            v = []
        if not isinstance(v, list):
            raise err("Cannot index %s with number" % typename(v))
        idx = math.floor(k)
        if idx < 0:
            idx += len(v)
            if idx < 0:
                raise err("Out of bounds negative array index")
        if idx > 536870911:
            raise err("Array index too large")
        r = list(v)
        if idx >= len(r):
            r.extend([None] * (idx + 1 - len(r)))
        r[idx] = setpath(r[idx], path, nv, i + 1)
        return r
    if isinstance(k, dict):
        if v is None:
            v = []
        if not isinstance(v, list):
            raise err("Cannot update field at object index of %s" % typename(v))
        a, b = _slice_bounds(len(v), k.get("start"), k.get("end"))
        new = setpath(v[a:b], path, nv, i + 1)
        if not isinstance(new, list):
            raise err("A slice of an array can only be assigned another array")
        return v[:a] + new + v[b:]
    if isinstance(v, dict):
        raise err("Cannot index object with %s" % typename(k))
    raise err("Invalid path component %s" % dump_trunc(k))


def delpath(v, path, i=0):
    if v is None:
        return None
    k = path[i]
    last = i == len(path) - 1
    if isinstance(k, str):
        if not isinstance(v, dict):
            raise err("Cannot delete field at object index of %s" % typename(v))
        if k not in v:
            return v
        r = dict(v)
        if last:
            del r[k]
        else:
            r[k] = delpath(v[k], path, i + 1)
        return r
    if isnum(k):
        if not isinstance(v, list):
            raise err("Cannot delete field at array index of %s" % typename(v))
        idx = math.floor(k)
        if idx < 0:
            idx += len(v)
        if idx < 0 or idx >= len(v):
            return v
        r = list(v)
        if last:
            del r[idx]
        else:
            r[idx] = delpath(v[idx], path, i + 1)
        return r
    if isinstance(k, dict):
        if not isinstance(v, list):
            raise err("Cannot delete field at object index of %s" % typename(v))
        a, b = _slice_bounds(len(v), k.get("start"), k.get("end"))
        if last:
            return v[:a] + v[b:]
        sub = delpath(v[a:b], path, i + 1)
        return v[:a] + sub + v[b:]
    raise err("Invalid path component %s" % dump_trunc(k))


def delpaths(v, paths):
    if not isinstance(paths, list):
        raise err("Paths must be specified as an array")
    for p in paths:
        if not isinstance(p, list):
            raise err("Path must be specified as an array")
    for p in sorted(paths, key=_pkey, reverse=True):
        if not p:
            return None
        v = delpath(v, p)
    return v


def _pkey(p):
    from .values import sort_key
    return sort_key(p)


def arith_err(a, b, what):
    return err("%s (%s) and %s (%s) cannot be %s" % (typename(a), dump_trunc(a),
                                                       typename(b), dump_trunc(b), what))


def op_add(a, b):
    ta, tb = type(a), type(b)
    if ta is int and tb is int:
        r = a + b
        return r if -9007199254740992 <= r <= 9007199254740992 else float(r)
    if a is None:
        return b
    if b is None:
        return a
    if isnum(a) and isnum(b):
        return norm_float(a + b)
    if ta is str and tb is str:
        return a + b
    if ta is list and tb is list:
        return a + b
    if ta is dict and tb is dict:
        r = dict(a)
        r.update(b)
        return r
    raise arith_err(a, b, "added")


def norm_float(x):
    if type(x) is float and x.is_integer() and abs(x) <= 9007199254740992 and not (x == 0 and math.copysign(1, x) < 0):
        return int(x)
    return x


def op_sub(a, b):
    if isnum(a) and isnum(b):
        return norm_float(norm_num(a - b) if type(a) is int and type(b) is int else a - b)
    if isinstance(a, list) and isinstance(b, list):
        return [x for x in a if not any(equals(x, y) for y in b)]
    raise arith_err(a, b, "subtracted")


def deep_merge(a, b):
    r = dict(a)
    for k, v in b.items():
        if k in r and isinstance(r[k], dict) and isinstance(v, dict):
            r[k] = deep_merge(r[k], v)
        else:
            r[k] = v
    return r


def op_mul(a, b):
    if isnum(a) and isnum(b):
        if type(a) is int and type(b) is int:
            return norm_num(a * b)
        try:
            return norm_float(a * b)
        except OverflowError:
            return math.inf
    if isinstance(a, str) and isnum(b) or isinstance(b, str) and isnum(a):
        s, n = (a, b) if isinstance(a, str) else (b, a)
        if n != n or n <= 0:
            return None if n != n or n < 0 else ""
        cnt = int(n) if n >= 1 else 1
        if cnt * len(s) > 1 << 30:
            raise err("Repeat string result too long")
        return s * cnt
    if isinstance(a, dict) and isinstance(b, dict):
        return deep_merge(a, b)
    raise arith_err(a, b, "multiplied")


def op_div(a, b):
    if isnum(a) and isnum(b):
        if b == 0:
            raise arith_err(a, b, "divided because the divisor is zero")
        return norm_float(a / b)
    if isinstance(a, str) and isinstance(b, str):
        return split_str(a, b)
    raise arith_err(a, b, "divided")


def split_str(a, sep):
    if a == "":
        return []
    if sep == "":
        return list(a)
    return a.split(sep)


def _toint(x):
    if x != x:
        return 0
    if x == math.inf:
        return 2 ** 63 - 1
    if x == -math.inf:
        return -2 ** 63
    return int(x)


def op_mod(a, b):
    if isnum(a) and isnum(b):
        if a != a or b != b:
            return math.nan
        ia, ib = _toint(a), _toint(b)
        if ib == 0:
            raise arith_err(a, b, "divided because the divisor is zero")
        r = abs(ia) % abs(ib)
        return -r if ia < 0 else r
    raise arith_err(a, b, "divided")


BINOPS = {
    "+": op_add, "-": op_sub, "*": op_mul, "/": op_div, "%": op_mod,
    "==": equals,
    "!=": lambda a, b: not equals(a, b),
    "<": lambda a, b: compare(a, b) < 0,
    "<=": lambda a, b: compare(a, b) <= 0,
    ">": lambda a, b: compare(a, b) > 0,
    ">=": lambda a, b: compare(a, b) >= 0,
}


# ------------------------------------------------------------ environments
class Env(object):
    __slots__ = ("parent", "key", "val")

    def __init__(self, parent, key, val):
        self.parent, self.key, self.val = parent, key, val


def env_lookup(env, key):
    while env is not None:
        if env.key == key:
            return env.val
        env = env.parent
    raise KeyError(key)


class Closure(object):
    __slots__ = ("params", "body", "env")

    def __init__(self, params, body, env):
        self.params, self.body, self.env = params, body, env


class Scope(object):
    """Compile-time scope: a linked list of (kind, name, arity)."""
    __slots__ = ("kind", "name", "arity", "parent")

    def __init__(self, kind, name, arity, parent):
        self.kind, self.name, self.arity, self.parent = kind, name, arity, parent


def scope_has(sc, kind, name, arity=0):
    while sc is not None:
        if sc.kind == kind and sc.name == name and sc.arity == arity:
            return True
        sc = sc.parent
    return False


def np(p):
    return None if p is None else NOPATH


def invalid_path(v):
    return err("Invalid path expression with result %s" % dump_trunc(v))


# ------------------------------------------------------------ compiler
class Compiler(object):
    def __init__(self, builtins):
        self.builtins = builtins   # object providing resolve(name, arity)

    def compile(self, node, sc):
        return getattr(self, "c_" + node[0])(node, sc)

    def c_id(self, node, sc):
        def f(env, p, v):
            yield p, v
        return f

    def c_paren(self, node, sc):
        return self.compile(node[1], sc)

    def c_lit(self, node, sc):
        val = node[1]

        def f(env, p, v):
            yield (None if p is None else NOPATH), val
        return f

    def c_neg(self, node, sc):
        a = self.compile(node[1], sc)

        def f(env, p, v):
            for _, x in a(env, None, v):
                if not isnum(x):
                    raise err("%s (%s) cannot be negated" % (typename(x), dump_trunc(x)))
                if type(x) is NumLit:
                    yield np(p), NumLit(-float(x), x.lit[1:] if x.lit.startswith("-") else "-" + x.lit)
                else:
                    yield np(p), (-x if x else NumLit(-0.0, "-0")) if type(x) is int else norm_float(-x)
        return f

    def c_pipe(self, node, sc):
        a = self.compile(node[1], sc)
        b = self.compile(node[2], sc)

        def f(env, p, v):
            for p1, v1 in a(env, p, v):
                yield from b(env, p1, v1)
        return f

    def c_comma(self, node, sc):
        a = self.compile(node[1], sc)
        b = self.compile(node[2], sc)

        def f(env, p, v):
            yield from a(env, p, v)
            yield from b(env, p, v)
        return f

    def c_index(self, node, sc):
        t = self.compile(node[1], sc)
        kn = node[2]
        if kn[0] == "lit":
            kv = kn[1]

            def f(env, p, v):
                for tp, tv in t(env, p, v):
                    r = index_value(tv, kv)
                    if p is None:
                        yield None, r
                    else:
                        if tp is NOPATH:
                            raise invalid_path(tv)
                        yield tp + (kv,), r
            return f
        k = self.compile(kn, sc)

        def f2(env, p, v):
            for _, kv in k(env, None, v):
                for tp, tv in t(env, p, v):
                    r = index_value(tv, kv)
                    if p is None:
                        yield None, r
                    else:
                        if tp is NOPATH:
                            raise invalid_path(tv)
                        yield tp + (kv,), r
        return f2

    def c_slice(self, node, sc):
        t = self.compile(node[1], sc)
        lo = self.compile(node[2], sc) if node[2] else None
        hi = self.compile(node[3], sc) if node[3] else None

        def f(env, p, v):
            his = [x for _, x in hi(env, None, v)] if hi else [None]
            los = [x for _, x in lo(env, None, v)] if lo else [None]
            for h in his:
                for l in los:
                    key = {"start": l, "end": h}
                    for tp, tv in t(env, p, v):
                        if tv is not None and not isinstance(tv, (list, str)):
                            raise err("Cannot index %s with object" % typename(tv))
                        r = index_value(tv, key)
                        if p is None:
                            yield None, r
                        else:
                            if tp is NOPATH:
                                raise invalid_path(tv)
                            yield tp + (key,), r
        return f

    def c_iter(self, node, sc):
        t = self.compile(node[1], sc)

        def f(env, p, v):
            for tp, tv in t(env, p, v):
                if p is None:
                    if isinstance(tv, list):
                        for x in tv:
                            yield None, x
                    elif isinstance(tv, dict):
                        for x in tv.values():
                            yield None, x
                    else:
                        raise err("Cannot iterate over %s%s" % (
                            typename(tv), "" if tv is None else " (%s)" % dump_trunc(tv)))
                else:
                    if tp is NOPATH:
                        raise invalid_path(tv)
                    for k, x in iterate(tv):
                        yield tp + (k,), x
        return f

    def c_try(self, node, sc):
        body = self.compile(node[1], sc)
        handler = self.compile(node[2], sc) if node[2] is not None else None

        def f(env, p, v):
            try:
                yield from body(env, p, v)
            except JQError as e:
                if handler is not None:
                    for _, hv in handler(env, None, e.value):
                        yield np(p), hv
        return f

    def c_binop(self, node, sc):
        op = BINOPS[node[1]]
        a = self.compile(node[2], sc)
        b = self.compile(node[3], sc)
        # constant folding of literals is unnecessary; keep generic
        simple_b = node[3][0] == "lit"
        simple_a = node[2][0] in ("lit", "id")
        if simple_a and simple_b:
            bv = node[3][1]
            if node[2][0] == "id":
                def f0(env, p, v):
                    yield np(p), op(v, bv)
                return f0

        def f(env, p, v):
            for _, y in b(env, None, v):
                for _, x in a(env, None, v):
                    yield np(p), op(x, y)
        return f

    def c_and(self, node, sc):
        a = self.compile(node[1], sc)
        b = self.compile(node[2], sc)

        def f(env, p, v):
            for _, x in a(env, None, v):
                if not truthy(x):
                    yield np(p), False
                else:
                    for _, y in b(env, None, v):
                        yield np(p), truthy(y)
        return f

    def c_or(self, node, sc):
        a = self.compile(node[1], sc)
        b = self.compile(node[2], sc)

        def f(env, p, v):
            for _, x in a(env, None, v):
                if truthy(x):
                    yield np(p), True
                else:
                    for _, y in b(env, None, v):
                        yield np(p), truthy(y)
        return f

    def c_alt(self, node, sc):
        a = self.compile(node[1], sc)
        b = self.compile(node[2], sc)

        def f(env, p, v):
            any_ = False
            try:
                for item in a(env, p, v):
                    if truthy(item[1]):
                        any_ = True
                        yield item
            except JQError:
                pass
            if not any_:
                yield from b(env, p, v)
        return f

    def c_if(self, node, sc):
        c = self.compile(node[1], sc)
        t = self.compile(node[2], sc)
        e = self.compile(node[3], sc) if node[3] is not None else None

        def f(env, p, v):
            for _, cv in c(env, None, v):
                if truthy(cv):
                    yield from t(env, p, v)
                elif e is not None:
                    yield from e(env, p, v)
                else:
                    yield p, v
        return f

    def c_array(self, node, sc):
        if node[1] is None:
            def f0(env, p, v):
                yield np(p), []
            return f0
        body = self.compile(node[1], sc)

        def f(env, p, v):
            yield np(p), [x for _, x in body(env, None, v)]
        return f

    def c_object(self, node, sc):
        ents = []
        for kn, vn in node[1]:
            ents.append((self.compile(kn, sc), self.compile(vn, sc)))

        def f(env, p, v):
            def build(i, acc):
                if i == len(ents):
                    yield acc
                    return
                kf, vf = ents[i]
                for _, k in kf(env, None, v):
                    if not isinstance(k, str):
                        raise err("Object keys must be strings")
                    for _, val in vf(env, None, v):
                        d = dict(acc)
                        d[k] = val
                        yield from build(i + 1, d)
            for o in build(0, {}):
                yield np(p), o
        return f

    def c_str(self, node, sc):
        fmt = node[1]
        parts = []
        for x in node[2]:
            parts.append(x if isinstance(x, str) else self.compile(x, sc))
        formatter = self.builtins.formatter(fmt or "@text")

        def f(env, p, v):
            def build(i, acc):
                if i < 0:
                    yield "".join(acc)
                    return
                x = parts[i]
                if isinstance(x, str):
                    yield from build(i - 1, [x] + acc)
                else:
                    for _, val in x(env, None, v):
                        yield from build(i - 1, [formatter(val)] + acc)
            for s in build(len(parts) - 1, []):
                yield np(p), s
        return f

    def c_format(self, node, sc):
        formatter = self.builtins.formatter(node[1])

        def f(env, p, v):
            yield np(p), formatter(v)
        return f

    def c_var(self, node, sc):
        name = node[1]
        if not scope_has(sc, "v", name):
            if name == "ENV":
                key = "$ENV"
                import os
                def fe(env, p, v):
                    yield np(p), dict(os.environ)
                return fe
            raise JQSyntaxError("$%s is not defined" % name)
        key = "$" + name

        def f(env, p, v):
            yield np(p), env_lookup(env, key)
        return f

    # ---- binding / patterns
    def pat_vars(self, pat, out):
        k = pat[0]
        if k == "pvar":
            out.append(pat[1])
        elif k == "parr":
            for x in pat[1]:
                self.pat_vars(x, out)
        else:
            for key, sub in pat[1]:
                if key[0] == "var":
                    out.append(key[1])
                if sub is not None:
                    self.pat_vars(sub, out)
        return out

    def compile_pattern(self, pat, sc):
        """Return fn(env, value, orig) -> generator of envs."""
        k = pat[0]
        if k == "pvar":
            key = "$" + pat[1]

            def f(env, val, orig):
                yield Env(env, key, val)
            return f
        if k == "parr":
            subs = [self.compile_pattern(x, sc) for x in pat[1]]

            def fa(env, val, orig):
                if val is not None and not isinstance(val, list):
                    raise err("Cannot index %s with number" % typename(val))

                def go(i, e):
                    if i == len(subs):
                        yield e
                        return
                    item = val[i] if val is not None and i < len(val) else None
                    for e2 in subs[i](e, item, orig):
                        yield from go(i + 1, e2)
                yield from go(0, env)
            return fa
        ents = []
        for key, sub in pat[1]:
            if key[0] == "var":
                ents.append(("var", key[1], None, self.compile_pattern(sub, sc) if sub else None))
            else:
                ents.append(("expr", None, self.compile(key, sc),
                             self.compile_pattern(sub, sc)))

        def fo(env, val, orig):
            def go(i, e):
                if i == len(ents):
                    yield e
                    return
                kind, name, kf, sub = ents[i]
                if kind == "var":
                    item = index_value(val, name)
                    e1 = Env(e, "$" + name, item)
                    if sub is None:
                        yield from go(i + 1, e1)
                    else:
                        for e2 in sub(e1, item, orig):
                            yield from go(i + 1, e2)
                else:
                    for _, kv in kf(e, None, orig):
                        if not isinstance(kv, str):
                            raise err("Cannot index %s with %s" % (typename(val), typename(kv)))
                        item = index_value(val, kv)
                        for e2 in sub(e, item, orig):
                            yield from go(i + 1, e2)
            yield from go(0, env)
        return fo

    def bind_machinery(self, pats, sc):
        """Returns (compiled pattern fns, all var names, new scope)."""
        names = []
        for pt in pats:
            for n in self.pat_vars(pt, []):
                if n not in names:
                    names.append(n)
        nsc = sc
        for n in names:
            nsc = Scope("v", n, 0, nsc)
        fns = [self.compile_pattern(pt, nsc if False else sc) for pt in pats]
        return fns, names, nsc

    def make_binder(self, pats, sc):
        fns, names, nsc = self.bind_machinery(pats, sc)
        pvars = [self.pat_vars(pt, []) for pt in pats]
        multi = len(pats) > 1

        def envs(env, val, orig):
            """Yield (env, alt_index) for each destructuring."""
            if not multi:
                yield from fns[0](env, val, orig)
                return
            raise AssertionError
        return fns, names, nsc, pvars

    def c_bind(self, node, sc):
        src = self.compile(node[1], sc)
        pats = node[2]
        fns, names, nsc, pvars = self.make_binder(pats, sc)
        body = self.compile(node[3], nsc)
        if len(pats) == 1:
            pf = fns[0]

            def f(env, p, v):
                for _, x in src(env, None, v):
                    for e2 in pf(env, x, v):
                        yield from body(e2, p, v)
            return f

        def fm(env, p, v):
            for _, x in src(env, None, v):
                for ai in range(len(pats)):
                    base = env
                    for n in names:
                        base = Env(base, "$" + n, None)
                    last = ai == len(pats) - 1
                    try:
                        for e2 in fns[ai](base, x, v):
                            yield from body(e2, p, v)
                        break
                    except JQError as e:
                        if last:
                            raise
                        continue
        return fm

    def c_reduce(self, node, sc):
        src = self.compile(node[1], sc)
        fns, names, nsc, pvars = self.make_binder(node[2], sc)
        init = self.compile(node[3], sc)
        upd = self.compile(node[4], nsc)
        pf = fns[0]

        def f(env, p, v):
            for ip, iv in init(env, p, v):
                sp, sv = ip, iv
                for _, x in src(env, None, v):
                    for e2 in pf(env, x, v):
                        last = None
                        got = False
                        for item in upd(e2, sp, sv):
                            last = item
                            got = True
                        if got:
                            sp, sv = last
                        else:
                            sp, sv = np(p), None
                yield sp, sv
        return f

    def c_foreach(self, node, sc):
        src = self.compile(node[1], sc)
        fns, names, nsc, pvars = self.make_binder(node[2], sc)
        init = self.compile(node[3], sc)
        upd = self.compile(node[4], nsc)
        ext = self.compile(node[5], nsc) if node[5] is not None else None
        pf = fns[0]

        def f(env, p, v):
            for ip, iv in init(env, p, v):
                sp, sv = ip, iv
                for _, x in src(env, None, v):
                    for e2 in pf(env, x, v):
                        for item in upd(e2, sp, sv):
                            sp, sv = item
                            if ext is None:
                                yield item
                            else:
                                yield from ext(e2, sp, sv)
        return f

    def c_label(self, node, sc):
        body = self.compile(node[2], Scope("l", node[1], 0, sc))
        key = "*label*" + node[1]

        def f(env, p, v):
            tok = object()
            try:
                yield from body(Env(env, key, tok), p, v)
            except BreakEx as b:
                if b.token is not tok:
                    raise
        return f

    def c_break(self, node, sc):
        if not scope_has(sc, "l", node[1]):
            raise JQSyntaxError("$*label-%s is not defined" % node[1])
        key = "*label*" + node[1]

        def f(env, p, v):
            raise BreakEx(env_lookup(env, key))
            yield
        return f

    # ---- functions
    def c_funcdef(self, node, sc):
        _, name, params, body, rest = node
        ar = len(params)
        key = "%s/%d" % (name, ar)
        bsc = Scope("f", name, ar, sc)
        for prm in params:
            if prm.startswith("$"):
                bsc = Scope("v", prm[1:], 0, bsc)
                bsc = Scope("f", prm[1:], 0, bsc)
            else:
                bsc = Scope("f", prm, 0, bsc)
        bodyfn = self.compile(body, bsc)
        restfn = self.compile(rest, Scope("f", name, ar, sc))
        cparams = tuple(params)

        def f(env, p, v):
            ne = Env(env, key, None)
            ne.val = Closure(cparams, bodyfn, ne)
            yield from restfn(ne, p, v)
        return f

    def c_call(self, node, sc):
        name, args = node[1], node[2]
        ar = len(args)
        if scope_has(sc, "f", name, ar):
            return self.user_call(name, args, sc)
        return self.builtins.resolve(self, name, args, sc)

    def user_call(self, name, args, sc):
        ar = len(args)
        key = "%s/%d" % (name, ar)
        argfns = [self.compile(a, sc) for a in args]
        if ar == 0:
            def f0(env, p, v):
                c = env_lookup(env, key)
                yield from c.body(c.env, p, v)
            return f0
        return make_call(lambda env: env_lookup(env, key), argfns)


def make_call(getc, argfns):
    def f(env, p, v):
        c = getc(env)
        params = c.params
        if not params:
            yield from c.body(c.env, p, v)
            return
        n = len(params)

        def bind(i, e):
            if i == n:
                yield from c.body(e, p, v)
                return
            prm = params[i]
            if prm[0] == "$":
                nm = prm[1:]
                for _, val in argfns[i](env, None, v):
                    e2 = Env(Env(e, "$" + nm, val), nm + "/0", Closure((), _const(val), None))
                    yield from bind(i + 1, e2)
            else:
                yield from bind(i + 1, Env(e, prm + "/0", Closure((), argfns[i], env)))
        yield from bind(0, c.env)
    return f


def _const(val):
    def f(env, p, v):
        yield (None if p is None else NOPATH), val
    return f


def _first_output(fn, env, v):
    for _, x in fn(env, None, v):
        return True, x
    return False, None


def _collect_paths(lhs, env, v):
    out = []
    for pp, pv in lhs(env, (), v):
        if pp is NOPATH:
            raise invalid_path(pv)
        out.append(list(pp))
    return out


def _compile_assign(self, node, sc):
    op = node[1]
    lhs = self.compile(node[2], sc)
    rhs = self.compile(node[3], sc)
    if op == "=":
        def f(env, p, v):
            for _, rv in rhs(env, None, v):
                acc = v
                for pth in _collect_paths(lhs, env, v):
                    acc = setpath(acc, pth, rv)
                yield np(p), acc
        return f
    if op == "|=":
        def fu(env, p, v):
            acc = v
            dels = []
            for pth in _collect_paths(lhs, env, v):
                ok, nv = _first_output(rhs, env, getpath(acc, pth))
                if ok:
                    acc = setpath(acc, pth, nv)
                else:
                    dels.append(pth)
            if dels:
                acc = delpaths(acc, dels)
            yield np(p), acc
        return fu
    bop = op[:-1]

    def fa(env, p, v):
        for _, rv in rhs(env, None, v):
            acc = v
            dels = []
            for pth in _collect_paths(lhs, env, v):
                cur = getpath(acc, pth)
                if bop == "//":
                    nv = cur if truthy(cur) else rv
                else:
                    nv = BINOPS[bop](cur, rv)
                acc = setpath(acc, pth, nv)
            yield np(p), acc
    return fa


Compiler.c_assign = _compile_assign
