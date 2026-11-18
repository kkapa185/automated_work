"""Expression compiler and SELECT planner/executor.

Expressions are compiled to Python closures taking the current flat row (a list: the columns of every
FROM source in order, each followed by that source's rowid slot). Correlated sub-queries see the rows of
enclosing queries through ``ctx.stack``.
"""
from operator import itemgetter
from .errors import SqlError, RaiseIgnore
from .catalog import Table, View, ROWID_NAMES
from . import values as V
from .values import (truth, compare, apply_affinity, sortkey, to_text, get_collation, type_affinity)
from . import functions as F


class Ctx:
    def __init__(self, db):
        self.db = db
        self.stack = []
        self.ctes = []
        self.trigger_stack = []


class Source:
    def __init__(self, alias, cols, affs=None, colls=None, table=None, rows_fn=None, plan=None, has_rowid=False):
        self.alias = alias
        self.cols = cols
        self.affs = affs or [None] * len(cols)
        self.colls = colls or [None] * len(cols)
        self.table = table
        self.rows_fn = rows_fn
        self.plan = plan
        self.has_rowid = has_rowid
        self.width = len(cols) + 1
        self.offset = 0
        self.hidden = set()


class Scope:
    def __init__(self, parent=None):
        self.sources = []
        self.parent = parent
        self.width = 0
        self.correlated = False
        self.aliases = {}

    def add(self, src):
        src.offset = self.width
        self.width += src.width
        self.sources.append(src)

    def find(self, tbl, name):
        ln = name.lower()
        lt = tbl.lower() if tbl else None
        found = []
        for si, s in enumerate(self.sources):
            if lt is not None and (s.alias or '').lower() != lt:
                continue
            hit = False
            for i, c in enumerate(s.cols):
                if c.lower() == ln:
                    if lt is None and i in s.hidden:
                        continue
                    found.append((si, s.offset + i))
                    hit = True
                    break
            if not hit and s.has_rowid and ln in ROWID_NAMES:
                found.append((si, s.offset + len(s.cols)))
        return found

    def pos_info(self, pos):
        for s in self.sources:
            if s.offset <= pos < s.offset + s.width:
                i = pos - s.offset
                if i < len(s.cols):
                    return s, i
                return s, -1
        return None, -1


def _is_agg_call(name, nargs, star):
    if name not in F.AGGREGATES:
        return False
    if name in ('min', 'max'):
        return nargs == 1
    return True


CMP_OPS = {
    '=': lambda c: c == 0, '!=': lambda c: c != 0, '<': lambda c: c < 0, '<=': lambda c: c <= 0,
    '>': lambda c: c > 0, '>=': lambda c: c >= 0,
}

NUMERIC_AFFS = ('INTEGER', 'REAL', 'NUMERIC')


def _numconv(v):
    return apply_affinity(v, 'NUMERIC')


def _textconv(v):
    return apply_affinity(v, 'TEXT')


def compare_convs(affa, affb):
    """Affinity conversions applied to the two operands of a comparison."""
    na = affa in NUMERIC_AFFS
    nb = affb in NUMERIC_AFFS
    if na and not nb:
        return None, _numconv
    if nb and not na:
        return _numconv, None
    if affa == 'TEXT' and (affb is None or affb == 'BLOB'):
        return None, _textconv
    if affb == 'TEXT' and (affa is None or affa == 'BLOB'):
        return _textconv, None
    return None, None


def split_and(node, out=None):
    if out is None:
        out = []
    if node is None:
        return out
    if node[0] == 'bin' and node[1] == 'AND':
        split_and(node[2], out)
        split_and(node[3], out)
    elif node[0] == 'paren' and node[1][0] == 'bin' and node[1][1] == 'AND':
        split_and(node[1], out)
    else:
        out.append(node)
    return out


def walk_cols(node, acc):
    """Collect column refs in an expression; append None if sub-selects/unknowns are present."""
    if isinstance(node, tuple):
        if node and node[0] == 'col':
            acc.append(node)
            return
        if node and node[0] in ('subq', 'exists', 'insub'):
            acc.append(None)
            if node[0] == 'insub':
                walk_cols(node[1], acc)
            return
        for x in node:
            walk_cols(x, acc)
    elif isinstance(node, list):
        for x in node:
            walk_cols(x, acc)
    elif isinstance(node, dict):
        acc.append(None)


def has_agg_or_window(node):
    """True if AST contains an aggregate call (outside sub-selects)."""
    if isinstance(node, tuple):
        if node and node[0] == 'func':
            if node[6] is None and _is_agg_call(node[1], len(node[2]), node[4]):
                return True
        if node and node[0] in ('subq', 'exists'):
            return False
        return any(has_agg_or_window(x) for x in node)
    if isinstance(node, list):
        return any(has_agg_or_window(x) for x in node)
    return False


class Comp:
    """Compiles expression ASTs against a Scope."""

    def __init__(self, ctx, scope, aggs=None, wins=None):
        self.ctx = ctx
        self.scope = scope
        self.aggs = aggs          # list collecting aggregate specs, or None if aggregates are illegal here
        self.wins = wins
        self.in_agg = False
        self.alias_depth = 0

    # ------------------------------------------------------------ name resolution
    def resolve(self, tbl, name):
        scope = self.scope
        depth = 0
        chain = []
        while scope is not None:
            found = scope.find(tbl, name)
            if len(found) > 1:
                raise SqlError('ambiguous column name: %s' % (tbl + '.' + name if tbl else name), 'parse')
            if found:
                for s in chain:
                    s.correlated = True
                return depth, found[0][1], scope, found[0][0]
            chain.append(scope)
            scope = scope.parent
            depth += 1
        raise SqlError('no such column: %s' % (tbl + '.' + name if tbl else name), 'parse')

    def try_resolve(self, tbl, name):
        try:
            return self.resolve(tbl, name)
        except SqlError:
            return None

    def col_info(self, node):
        """(affinity, collation name) for a column ref node, or (None, None)."""
        if node[0] == 'col':
            r = self.try_resolve(node[1], node[2])
            if r is None:
                return None, None
            depth, pos, scope, si = r
        elif node[0] == 'pos':
            scope = self.scope
            pos = node[1]
        else:
            return None, None
        s, i = scope.pos_info(pos)
        if s is None:
            return None, None
        if i < 0:
            return 'INTEGER', None
        return s.affs[i], s.colls[i]

    def aff_of(self, node):
        t = node[0]
        if t == 'col' or t == 'pos':
            a = self.col_info(node)[0]
            return None if a == 'BLOB' else a
        if t == 'cast':
            a = type_affinity(node[2])
            return None if a == 'BLOB' else a
        if t == 'paren' or t == 'collate':
            return self.aff_of(node[1])
        if t == 'un' and node[1] == '+':
            return self.aff_of(node[2])
        return None

    def coll_of(self, node):
        """(collation name, explicit?) for an operand."""
        t = node[0]
        if t == 'collate':
            return node[2].upper(), True
        if t == 'col' or t == 'pos':
            c = self.col_info(node)[1]
            return (c.upper() if c else None), False
        if t == 'paren':
            return self.coll_of(node[1])
        if t == 'un' and node[1] == '+':
            return self.coll_of(node[2])
        return None, False

    def pair_collation(self, a, b):
        ca, ea = self.coll_of(a)
        cb, eb = self.coll_of(b)
        if ea:
            return ca
        if eb:
            return cb
        if ca:
            return ca
        if cb:
            return cb
        return None

    # ------------------------------------------------------------ main dispatch
    def comp(self, node):
        m = getattr(self, 'c_' + node[0], None)
        if m is None:
            raise SqlError('unsupported expression: %s' % node[0], 'parse')
        return m(node)

    def c_lit(self, node):
        v = node[1]
        return lambda r: v

    def c_paren(self, node):
        return self.comp(node[1])

    def c_collate(self, node):
        get_collation(node[2])
        return self.comp(node[1])

    def c_pos(self, node):
        return itemgetter(node[1])

    def c_col(self, node):
        if node[1] is not None and self.ctx.trigger_stack and node[1].lower() in ('new', 'old'):
            frame = self.ctx.trigger_stack[-1]
            which = node[1].lower()
            row = frame[which]
            name = node[2].lower()
            if row is None or (name not in frame['cols'] and name not in ROWID_NAMES):
                raise SqlError('no such column: %s.%s' % (node[1], node[2]), 'parse')
            idx = frame['cols'].index(name) if name in frame['cols'] else len(frame['cols'])
            return lambda r: row[idx]
        try:
            depth, pos, scope, si = self.resolve(node[1], node[2])
        except SqlError:
            # fall back to a result-column alias (only for unqualified names)
            if node[1] is None:
                al = self.scope.aliases.get(node[2].lower())
                if al is not None and self.alias_depth < 5:
                    self.alias_depth += 1
                    try:
                        return self.comp(al)
                    finally:
                        self.alias_depth -= 1
            raise
        if depth == 0:
            return itemgetter(pos)
        stack = self.ctx.stack
        d = depth
        return lambda r: stack[-d][pos]

    def c_un(self, node):
        op = node[1]
        f = self.comp(node[2])
        if op == 'NOT':
            def g(r):
                t = truth(f(r))
                return None if t is None else (0 if t else 1)
            return g
        if op == '-':
            return lambda r: V.neg(f(r))
        if op == '+':
            return f
        return lambda r: V.bitnot(f(r))

    ARITH = {'+': V.add, '-': V.sub, '*': V.mul, '/': V.div, '%': V.mod, '||': V.concat, '&': V.bit_and,
             '|': V.bit_or, '<<': V.shift_left, '>>': V.shift_right}

    def c_bin(self, node):
        op = node[1]
        if op == 'AND':
            lf = self.comp(node[2])
            rf = self.comp(node[3])

            def f_and(r):
                a = truth(lf(r))
                if a is False:
                    return 0
                b = truth(rf(r))
                if b is False:
                    return 0
                if a is None or b is None:
                    return None
                return 1
            return f_and
        if op == 'OR':
            lf = self.comp(node[2])
            rf = self.comp(node[3])

            def f_or(r):
                a = truth(lf(r))
                if a is True:
                    return 1
                b = truth(rf(r))
                if b is True:
                    return 1
                if a is None or b is None:
                    return None
                return 0
            return f_or
        if op in self.ARITH:
            fn = self.ARITH[op]
            lf = self.comp(node[2])
            rf = self.comp(node[3])
            return lambda r: fn(lf(r), rf(r))
        if op in ('->', '->>'):
            raise SqlError('JSON operators are not supported', 'parse')
        if op in ('IS', 'ISNOT'):
            return self.comp_is(node)
        return self.comp_cmp(op, node[2], node[3])

    def comparison_parts(self, ln, rn):
        ca, cb = compare_convs(self.aff_of(ln), self.aff_of(rn))
        cname = self.pair_collation(ln, rn)
        ck = get_collation(cname) if cname else None
        return ca, cb, ck

    @staticmethod
    def row_compare_ast(op, la, ra):
        """Expand a row-value comparison into scalar comparisons."""
        n = len(la)
        if op in ('=', '!='):
            node = None
            for x, y in zip(la, ra):
                c = ('bin', '=', x, y)
                node = c if node is None else ('bin', 'AND', node, c)
            return node if op == '=' else ('un', 'NOT', node)
        strict = '<' if op in ('<', '<=') else '>'
        node = ('bin', op, la[-1], ra[-1])
        for i in range(n - 2, -1, -1):
            node = ('bin', 'OR', ('bin', strict, la[i], ra[i]),
                    ('bin', 'AND', ('bin', '=', la[i], ra[i]), node))
        return node

    def comp_cmp(self, op, ln, rn):
        if ln[0] == 'row' or rn[0] == 'row':
            if ln[0] != 'row' or rn[0] != 'row' or len(ln[1]) != len(rn[1]):
                raise SqlError('row value misused', 'parse')
            return self.comp(self.row_compare_ast(op, ln[1], rn[1]))
        lf = self.comp(ln)
        rf = self.comp(rn)
        ca, cb, ck = self.comparison_parts(ln, rn)
        test = CMP_OPS[op]
        if ca is None and cb is None and ck is None:
            if op == '=':
                def f_eq(r):
                    a = lf(r)
                    b = rf(r)
                    if a is None or b is None:
                        return None
                    ta = type(a)
                    if ta is type(b) and (ta is int or ta is str):
                        return 1 if a == b else 0
                    return 1 if compare(a, b) == 0 else 0
                return f_eq

            def f_plain(r):
                a = lf(r)
                b = rf(r)
                if a is None or b is None:
                    return None
                return 1 if test(compare(a, b)) else 0
            return f_plain

        def f_cmp(r):
            a = lf(r)
            b = rf(r)
            if a is None or b is None:
                return None
            if ca is not None:
                a = ca(a)
            if cb is not None:
                b = cb(b)
            return 1 if test(compare(a, b, ck)) else 0
        return f_cmp

    def comp_is(self, node):
        lf = self.comp(node[2])
        rf = self.comp(node[3])
        ca, cb, ck = self.comparison_parts(node[2], node[3])
        neg = node[1] == 'ISNOT'

        def f(r):
            a = lf(r)
            b = rf(r)
            if a is None or b is None:
                eq = a is None and b is None
            else:
                if ca is not None:
                    a = ca(a)
                if cb is not None:
                    b = cb(b)
                eq = compare(a, b, ck) == 0
            return (0 if eq else 1) if neg else (1 if eq else 0)
        return f

    def c_isnull(self, node):
        f = self.comp(node[1])
        if node[2]:
            return lambda r: 0 if f(r) is None else 1
        return lambda r: 1 if f(r) is None else 0

    def c_between(self, node):
        _, e, lo, hi, neg = node
        n = ('bin', 'AND', ('bin', '>=', e, lo), ('bin', '<=', e, hi))
        if neg:
            n = ('un', 'NOT', n)
        return self.comp(n)

    def c_case(self, node):
        _, base, whens, els = node
        conds = []
        for w, t in whens:
            if base is not None:
                cf = self.comp_cmp('=', base, w)
            else:
                cf = self.comp(w)
            conds.append((cf, self.comp(t)))
        ef = self.comp(els) if els is not None else None

        def f(r):
            for cf, tf in conds:
                if truth(cf(r)):
                    return tf(r)
            return ef(r) if ef is not None else None
        return f

    def c_cast(self, node):
        f = self.comp(node[1])
        ty = node[2]
        return lambda r: V.cast_value(f(r), ty)

    def c_like(self, node):
        _, kw, e, pat, esc, neg = node
        if kw not in ('LIKE', 'GLOB'):
            raise SqlError('no such function: %s' % kw, 'parse')
        ef = self.comp(e)
        pf = self.comp(pat)
        escf = self.comp(esc) if esc is not None else None
        if kw == 'LIKE':
            def f(r):
                return F.like(ef(r), pf(r), escf(r) if escf else None)
        else:
            def f(r):
                return F.glob(ef(r), pf(r))
        if neg:
            def g(r):
                v = f(r)
                return None if v is None else 1 - v
            return g
        return f

    def c_inlist(self, node):
        _, e, items, neg = node
        if e[0] == 'row':
            if not all(it[0] == 'row' and len(it[1]) == len(e[1]) for it in items):
                raise SqlError('row value misused', 'parse')
            n2 = None
            for it in items:
                c = self.row_compare_ast('=', e[1], it[1])
                n2 = c if n2 is None else ('bin', 'OR', n2, c)
            if n2 is None:
                return lambda r: 1 if neg else 0
            return self.comp(('un', 'NOT', n2) if neg else n2)
        ef = self.comp(e)
        aff_e = self.aff_of(e)
        cname = self.coll_of(e)[0]
        ck = get_collation(cname) if cname else None
        itemfs = []
        consts = []
        allconst = True
        for it in items:
            ca, cb = compare_convs(aff_e, self.aff_of(it))
            itemfs.append((self.comp(it), ca, cb))
            if it[0] != 'lit':
                allconst = False
        if not items:
            return lambda r: 1 if neg else 0
        if allconst:
            ca, cb = compare_convs(aff_e, None)
            keyf = (lambda v: ck(v) if (ck and type(v) is str) else v)
            vals = set()
            has_null = False
            for it in items:
                v = it[1]
                if v is None:
                    has_null = True
                    continue
                if cb:
                    v = cb(v)
                vals.add(keyf(v))

            def f_const(r):
                v = ef(r)
                if v is None:
                    return None
                if ca:
                    v = ca(v)
                if keyf(v) in vals:
                    return 0 if neg else 1
                if has_null:
                    return None
                return 1 if neg else 0
            return f_const

        def f(r):
            v = ef(r)
            if v is None:
                return None
            seen_null = False
            for itf, ca, cb in itemfs:
                w = itf(r)
                if w is None:
                    seen_null = True
                    continue
                a = ca(v) if ca else v
                b = cb(w) if cb else w
                if compare(a, b, ck) == 0:
                    return 0 if neg else 1
            if seen_null:
                return None
            return 1 if neg else 0
        return f

    # ---- sub-queries
    def sub_plan(self, sel):
        child = Scope(self.scope)
        plan = compile_select(sel, self.ctx, self.scope)
        return plan

    def c_subq(self, node):
        plan = self.sub_plan(node[1])
        if plan.ncols != 1:
            raise SqlError('sub-select returns %d columns - expected 1' % plan.ncols, 'parse')
        stack = self.ctx.stack
        plan.limit_hint = 1
        corr = plan.correlated
        cache = []

        def f(r):
            if not corr and cache:
                return cache[0]
            stack.append(r)
            try:
                for row in plan.iter():
                    v = row[0]
                    break
                else:
                    v = None
            finally:
                stack.pop()
            if not corr:
                cache.append(v)
            return v
        return f

    def c_exists(self, node):
        plan = self.sub_plan(node[1])
        stack = self.ctx.stack
        plan.limit_hint = 1
        neg = node[2]
        corr = plan.correlated
        cache = []

        def f(r):
            if not corr and cache:
                return cache[0]
            stack.append(r)
            try:
                found = False
                for row in plan.iter():
                    found = True
                    break
            finally:
                stack.pop()
            v = (0 if found else 1) if neg else (1 if found else 0)
            if not corr:
                cache.append(v)
            return v
        return f

    def c_insub(self, node):
        _, e, sel, neg = node
        ef = self.comp(e)
        plan = self.sub_plan(sel)
        if plan.ncols != 1:
            raise SqlError('sub-select returns %d columns - expected 1' % plan.ncols, 'parse')
        stack = self.ctx.stack
        aff_e = self.aff_of(e)
        ca, cb = compare_convs(aff_e, plan.col_aff(0) if hasattr(plan, 'col_aff') else None)
        cname = self.coll_of(e)[0]
        ck = get_collation(cname) if cname else None
        keyf = (lambda v: ck(v) if (ck and type(v) is str) else v)
        corr = plan.correlated
        cache = []

        def build(r):
            stack.append(r)
            try:
                vals = set()
                has_null = False
                for row in plan.iter():
                    v = row[0]
                    if v is None:
                        has_null = True
                    else:
                        if cb:
                            v = cb(v)
                        vals.add(keyf(v))
            finally:
                stack.pop()
            return vals, has_null

        def f(r):
            v = ef(r)
            if corr or not cache:
                res = build(r)
                if not corr:
                    cache.append(res)
            else:
                res = cache[0]
            vals, has_null = res
            if v is None:
                return None if (vals or has_null) else (1 if neg else 0)
            if ca:
                v = ca(v)
            if keyf(v) in vals:
                return 0 if neg else 1
            if has_null:
                return None
            return 1 if neg else 0
        return f

    def c_row(self, node):
        raise SqlError('row value misused', 'parse')

    def c_raise(self, node):
        if not self.ctx.trigger_stack:
            raise SqlError('RAISE() may only be used within a trigger-program', 'parse')
        kind, msg = node[1], node[2]

        def f(r):
            if kind == 'IGNORE':
                raise RaiseIgnore()
            e = SqlError(msg)
            e.rollback = kind == 'ROLLBACK'
            raise e
        return f

    # ---- functions
    def c_func(self, node):
        _, name, args, distinct, star, flt, over = node
        n = len(args)
        if over is not None:
            return self.comp_window(node)
        if _is_agg_call(name, n, star):
            return self.comp_agg(node)
        if name in F.SPECIAL:
            lo, hi = F.SPECIAL[name]
            if n < lo or (hi >= 0 and n > hi):
                raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
            return self.comp_special(name, args)
        if name in ('current_time', 'current_date', 'current_timestamp'):
            fn = {'current_time': F.f_time, 'current_date': F.f_date, 'current_timestamp': F.f_datetime}[name]
            return lambda r: fn('now')
        if name in F.SCALARS:
            lo, hi, fn = F.SCALARS[name]
            if n < lo or (hi >= 0 and n > hi) or star or distinct:
                raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
            fs = [self.comp(a) for a in args]
            if n == 1:
                f0 = fs[0]
                return lambda r: fn(f0(r))
            if n == 2:
                f0, f1 = fs
                return lambda r: fn(f0(r), f1(r))
            return lambda r: fn(*[f(r) for f in fs])
        if name in F.AGGREGATES:
            raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
        raise SqlError('no such function: %s' % name, 'parse')

    def comp_special(self, name, args):
        db = self.ctx.db
        if name == 'last_insert_rowid':
            return lambda r: db.last_insert_rowid
        if name == 'changes':
            return lambda r: db.changes
        if name == 'total_changes':
            return lambda r: db.total_changes
        fs = [self.comp(a) for a in args]
        if name in ('coalesce', 'ifnull'):
            def f(r):
                for g in fs:
                    v = g(r)
                    if v is not None:
                        return v
                return None
            return f
        if name in ('iif', 'if'):
            c, a, b = fs
            return lambda r: a(r) if truth(c(r)) else b(r)
        # multi-argument min / max
        is_max = name == 'max'
        cks = [self.coll_of(a)[0] for a in args]
        cname = next((c for c in cks if c), None)
        ck = get_collation(cname) if cname else None

        def f(r):
            best = None
            first = True
            for g in fs:
                v = g(r)
                if v is None:
                    return None
                if first:
                    best = v
                    first = False
                else:
                    c = compare(v, best, ck)
                    if (c > 0) if is_max else (c < 0):
                        best = v
            return best
        return f

    def comp_agg(self, node):
        _, name, args, distinct, star, flt, over = node
        if self.aggs is None:
            raise SqlError('misuse of aggregate function %s()' % name, 'parse')
        if self.in_agg:
            raise SqlError('misuse of aggregate function %s()' % name, 'parse')
        n = len(args)
        if name == 'count':
            if star:
                if n:
                    raise SqlError('wrong number of arguments to function count()', 'parse')
            elif n != 1:
                raise SqlError('wrong number of arguments to function count()', 'parse')
        elif name in ('group_concat', 'string_agg'):
            if n not in (1, 2) or star:
                raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
            if distinct and n == 2:
                raise SqlError('DISTINCTs are not supported for functions with 2 arguments' if False else
                               'DISTINCT aggregates must have exactly one argument', 'parse')
        elif n != 1 or star:
            raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
        self.in_agg = True
        try:
            argfs = [self.comp(a) for a in args]
            flf = self.comp(flt) if flt is not None else None
        finally:
            self.in_agg = False
        cls = F.AggCountStar if (name == 'count' and star) else F.AGGREGATES[name]
        ck = None
        if name in ('min', 'max'):
            cn = self.coll_of(args[0])[0]
            ck = get_collation(cn) if cn else None
        if name == 'string_agg' and n != 2:
            raise SqlError('wrong number of arguments to function string_agg()', 'parse')
        idx = len(self.aggs)
        self.aggs.append((cls, argfs, distinct, flf, ck, name))
        slot = self.scope.width + idx
        return itemgetter(slot)

    def comp_window(self, node):
        if self.wins is None:
            raise SqlError('misuse of window function %s()' % node[1], 'parse')
        return self.wins.register(self, node)


# ====================================================================== SELECT planning
class Cte:
    def __init__(self, name, cols, sel, recursive):
        self.name = name
        self.cols = cols
        self.sel = sel
        self.recursive = recursive
        self.slot = None


class RecSlot:
    def __init__(self):
        self.rows = []


def find_cte(ctx, name):
    ln = name.lower()
    for d in reversed(ctx.ctes):
        if ln in d:
            return d[ln]
    return None


def compile_select(sel, ctx, parent_scope):
    pushed = False
    if sel.get('with'):
        rec, ctes = sel['with']
        d = {}
        ctx.ctes.append(d)
        pushed = True
        for name, cols, csel in ctes:
            d[name.lower()] = Cte(name, cols, csel, rec)
    try:
        plan = compile_body(sel['body'], sel, ctx, parent_scope)
    finally:
        if pushed:
            ctx.ctes.pop()
    return plan


def eval_limit(fn):
    v = fn([])
    if v is None:
        raise SqlError('datatype mismatch')
    if type(v) is not int:
        if type(v) is float and v.is_integer():
            v = int(v)
        elif type(v) is str:
            n = V.text_numeric_whole(v)
            if type(n) is int:
                v = n
            elif type(n) is float and n.is_integer():
                v = int(n)
            else:
                raise SqlError('datatype mismatch')
        else:
            raise SqlError('datatype mismatch')
    return v


class LimitMixin:
    def setup_limits(self, sel, ctx, parent_scope):
        self.limit_fn = self.offset_fn = None
        sc = Scope(parent_scope)
        if sel.get('limit') is not None:
            self.limit_fn = Comp(ctx, sc).comp(sel['limit'])
        if sel.get('offset') is not None:
            self.offset_fn = Comp(ctx, sc).comp(sel['offset'])

    def limits(self):
        lim = off = None
        if self.limit_fn is not None:
            lim = eval_limit(self.limit_fn)
            if lim < 0:
                lim = None
        if self.offset_fn is not None:
            off = eval_limit(self.offset_fn)
            if off < 0:
                off = 0
        return lim, off


def sort_rows(items, terms):
    """items: list of (out, keys); terms: list of (desc, nulls_first, ck). Stable multi-key sort."""
    for ti in range(len(terms) - 1, -1, -1):
        desc, nf, ck = terms[ti]
        null_low = (nf == (not desc)) if nf is not None else True
        low = (0,)
        high = (2,)
        nl = low if null_low else high

        def kf(item, ti=ti, ck=ck, nl=nl):
            v = item[1][ti]
            if v is None:
                return nl
            return (1, sortkey(v, ck))
        items.sort(key=kf, reverse=desc)
    return items


class BasePlan(LimitMixin):
    limit_hint = None
    correlated = False
    names = ()

    @property
    def ncols(self):
        return len(self.names)

    def run(self):
        return list(self.iter())

    def col_aff(self, i):
        return None


class ValuesPlan(BasePlan):
    def __init__(self, body, sel, ctx, parent_scope):
        scope = Scope(parent_scope)
        comp = Comp(ctx, scope)
        self.rows = [[comp.comp(e) for e in row] for row in body['rows']]
        n = len(self.rows[0])
        for r in self.rows:
            if len(r) != n:
                raise SqlError('all VALUES must have the same number of terms', 'parse')
        self.names = ['column%d' % (i + 1) for i in range(n)]
        self.scope = scope
        self.ctx = ctx
        self.order = sel.get('order')
        self.setup_limits(sel, ctx, parent_scope)
        self.sort_terms = None
        if self.order:
            self.sort_terms = resolve_output_order(self.order, self.names, None, comp)

    @property
    def correlated(self):
        return self.scope.correlated

    def iter(self):
        out = [tuple([f([]) for f in row]) for row in self.rows]
        return apply_order_limit(self, out)


def resolve_output_order(order, names, comp, comp2):
    """ORDER BY on a compound/VALUES: each term must designate an output column."""
    terms = []
    lnames = [n.lower() for n in names]
    for e, desc, nulls in order:
        ck = None
        while e[0] in ('collate', 'paren'):
            if e[0] == 'collate':
                ck = get_collation(e[2])
            e = e[1]
        if e[0] == 'lit' and type(e[1]) is int:
            if not 1 <= e[1] <= len(names):
                raise SqlError('%s ORDER BY term out of range - should be between 1 and %d'
                               % (_ordinal(e[1]), len(names)), 'parse')
            idx = e[1] - 1
        elif e[0] == 'col' and e[1] is None and e[2].lower() in lnames:
            idx = lnames.index(e[2].lower())
        else:
            raise SqlError('%s ORDER BY term does not match any column in the result set'
                           % _ordinal(len(terms) + 1), 'parse')
        terms.append((idx, desc, nulls == 'FIRST' if nulls else None, ck))
    return terms


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        suf = 'th'
    else:
        suf = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return '%d%s' % (n, suf)


def apply_order_limit(plan, rows):
    if plan.sort_terms:
        items = [(r, [r[t[0]] for t in plan.sort_terms]) for r in rows]
        sort_rows(items, [(t[1], t[2], t[3]) for t in plan.sort_terms])
        rows = [i[0] for i in items]
    lim, off = plan.limits()
    if off:
        rows = rows[off:]
    if lim is not None:
        rows = rows[:lim]
    return rows


class CompoundPlan(BasePlan):
    def __init__(self, body, sel, ctx, parent_scope):
        self.parts = []
        self.ops = []
        self._flatten(body, sel, ctx, parent_scope)
        self.names = self.parts[0].names
        n = self.parts[0].ncols
        for p in self.parts:
            if p.ncols != n:
                raise SqlError('SELECTs to the left and right of %s do not have the same number of result columns'
                               % self.ops[0] if self.ops else 'compound', 'parse')
        self.ctx = ctx
        self.setup_limits(sel, ctx, parent_scope)
        self.sort_terms = None
        if sel.get('order'):
            self.sort_terms = resolve_output_order(sel['order'], self.names, None, None)

    def _flatten(self, body, sel, ctx, parent_scope):
        if body['kind'] == 'compound':
            self._flatten(body['left'], sel, ctx, parent_scope)
            self.ops.append(body['op'])
            self.parts.append(compile_body(body['right'], {'order': None, 'limit': None, 'offset': None},
                                           ctx, parent_scope))
        else:
            self.parts.append(compile_body(body, {'order': None, 'limit': None, 'offset': None}, ctx, parent_scope))

    @property
    def correlated(self):
        return any(p.correlated for p in self.parts)

    def iter(self):
        rows = self.parts[0].run()
        for op, part in zip(self.ops, self.parts[1:]):
            other = part.run()
            if op == 'UNION ALL':
                rows = rows + other
                continue
            if op == 'UNION':
                seen = {}
                for r in rows + other:
                    seen.setdefault(r, r)
                rows = list(seen.values())
            elif op == 'INTERSECT':
                oset = set(other)
                seen = {}
                for r in rows:
                    if r in oset:
                        seen.setdefault(r, r)
                rows = list(seen.values())
            else:
                oset = set(other)
                seen = {}
                for r in rows:
                    if r not in oset:
                        seen.setdefault(r, r)
                rows = list(seen.values())
            rows.sort(key=V.row_sortkey)
        return apply_order_limit(self, rows)


def compile_body(body, sel, ctx, parent_scope):
    k = body['kind']
    if k == 'core':
        return CorePlan(body, sel, ctx, parent_scope)
    if k == 'values':
        return ValuesPlan(body, sel, ctx, parent_scope)
    return CompoundPlan(body, sel, ctx, parent_scope)


# ---------------------------------------------------------------------- CTE / views
class RecursiveCtePlan(BasePlan):
    """Plan for a recursive CTE: initial select(s) UNION [ALL] recursive select(s)."""

    def __init__(self, cte, ctx):
        self.ctx = ctx
        body = cte.sel['body']
        if body['kind'] != 'compound' or body['op'] not in ('UNION', 'UNION ALL'):
            raise SqlError('recursive CTE must be a compound SELECT using UNION [ALL]' if False else
                           'circular reference: %s' % cte.name, 'parse')
        self.slot = RecSlot()
        d = {cte.name.lower(): cte}
        cte.slot = self.slot
        self.union_all = body['op'] == 'UNION ALL'
        ctx.ctes.append(d)
        try:
            self.initial = compile_body(body['left'], {'order': None, 'limit': None, 'offset': None}, ctx, None)
            cte.slot_names = list(cte.cols) if cte.cols else list(self.initial.names)
            self.recursive = compile_body(body['right'], {'order': None, 'limit': None, 'offset': None}, ctx, None)
        finally:
            ctx.ctes.pop()
        self.names = list(cte.cols) if cte.cols else list(self.initial.names)
        if len(self.names) != self.initial.ncols or self.recursive.ncols != self.initial.ncols:
            raise SqlError('table %s has %d values for %d columns' % (cte.name, self.initial.ncols, len(self.names)),
                           'parse')
        self.setup_limits(cte.sel, ctx, None)
        self.order = cte.sel.get('order')
        self.sort_terms = resolve_output_order(self.order, self.names, None, None) if self.order else None

    def gen(self):
        lim, off = self.limits()
        seen = set() if not self.union_all else None
        queue = []
        produced = 0
        skipped = 0
        slot = self.slot
        for r in self.initial.iter():
            if seen is not None:
                if r in seen:
                    continue
                seen.add(r)
            queue.append(r)
        head = 0
        while head < len(queue):
            r = queue[head]
            head += 1
            if off and skipped < off:
                skipped += 1
            else:
                if lim is not None and produced >= lim:
                    return
                yield r
                produced += 1
                if lim is not None and produced >= lim:
                    return
            slot.rows = [r]
            for nr in self.recursive.iter():
                if seen is not None:
                    if nr in seen:
                        continue
                    seen.add(nr)
                queue.append(nr)
            if head > 4096:
                del queue[:head]
                head = 0

    def iter(self):
        if self.sort_terms:
            rows = list(self._all())
            return apply_order_limit(self, rows)
        return self.gen()

    def _all(self):
        saved = (self.limit_fn, self.offset_fn)
        self.limit_fn = self.offset_fn = None
        try:
            return list(self.gen())
        finally:
            self.limit_fn, self.offset_fn = saved


class RecRefPlan(BasePlan):
    """Reference to the working table inside the recursive step."""

    def __init__(self, cte, names):
        self.slot = cte.slot
        self.names = names

    def iter(self):
        return iter(list(self.slot.rows))


def cte_source(cte, alias, ctx):
    if cte.slot is not None:
        # reference to itself within the recursive step
        names = list(cte.cols) if cte.cols else cte.slot_names
        plan = RecRefPlan(cte, names)
    else:
        if cte_is_recursive(cte):
            plan = RecursiveCtePlan(cte, ctx)
            cte.slot_names = plan.names
            cte.slot = None
        else:
            saved = ctx.ctes
            ctx.ctes = [d for d in saved]
            # a non-recursive CTE sees only the CTEs defined before it
            plan = compile_select(cte.sel, ctx, None)
            ctx.ctes = saved
            if cte.cols:
                if len(cte.cols) != plan.ncols:
                    raise SqlError('table %s has %d values for %d columns' % (cte.name, plan.ncols, len(cte.cols)),
                                   'parse')
                plan.names = list(cte.cols)
    return plan_source(plan, alias or cte.name)


def cte_is_recursive(cte):
    """Whether the CTE body references its own name."""
    name = cte.name.lower()

    def walk(node):
        if isinstance(node, dict):
            if node.get('kind') == 'core' and node.get('from') is not None and walk_from(node['from']):
                return True
            return any(walk(v) for v in node.values() if isinstance(v, (dict, list, tuple)))
        if isinstance(node, (list, tuple)):
            return any(walk(v) for v in node)
        return False

    def walk_from(f):
        if f[0] == 'table':
            return f[1].lower() == name
        if f[0] == 'subq':
            return walk(f[1])
        if f[0] == 'join':
            return walk_from(f[1]) or walk_from(f[2])
        return False
    return walk(cte.sel)


def plan_source(plan, alias):
    src = Source(alias, list(plan.names), plan=plan)
    corr = plan.correlated

    def rows_fn():
        for row in plan.iter():
            yield list(row) + [None]
    src.rows_fn = rows_fn
    return src


# ---------------------------------------------------------------------- FROM
class Step:
    def __init__(self, src, jtype, on, using, natural):
        self.src = src
        self.jtype = jtype
        self.on = on
        self.using = using
        self.natural = natural
        self.cands = []      # equality candidates (colpos|-1 for rowid, valfn, conv, index, ...)
        self.filters = []


def flatten_from(node, out):
    if node[0] == 'join':
        flatten_from(node[1], out)
        right = node[2]
        if right[0] == 'join':
            raise SqlError('parenthesised joins on the right-hand side are not supported', 'parse')
        out.append((right, node[3], node[4], node[5], node[6]))
    else:
        out.append((node, None, None, None, False))
    return out


class FromPlan:
    def __init__(self, ctx, scope, node, where):
        self.ctx = ctx
        self.scope = scope
        self.steps = []
        self.where_filters = []   # (level, fn) pushed-down conjuncts
        self.final_filters = []
        if node is None:
            self.comp = Comp(ctx, scope)
            self.empty = True
            self.has_outer_right = False
            self.empty_filters = [self.comp.comp(c) for c in split_and(where)]
            return
        self.empty = False
        items = flatten_from(node, [])
        for leaf, jt, on, using, natural in items:
            src = self.make_source(leaf)
            step = Step(src, jt, on, using, natural)
            self.steps.append(step)
            scope.add(src)
        self.comp = Comp(ctx, scope)
        self.has_outer_right = any(s.jtype in ('RIGHT', 'FULL') for s in self.steps)
        self.prepare_joins()
        self.plan_where(where)

    # ---- sources
    def make_source(self, leaf):
        ctx = self.ctx
        if leaf[0] == 'subq':
            plan = compile_select(leaf[1], ctx, self.scope.parent)
            alias = leaf[2]
            return plan_source(plan, alias)
        name, alias = leaf[1], leaf[2]
        cte = find_cte(ctx, name)
        if cte is not None:
            return cte_source(cte, alias or name, ctx)
        rel = ctx.db.find_relation(name)
        if rel is None:
            raise SqlError('no such table: %s' % name, 'parse')
        if isinstance(rel, View):
            saved = ctx.ctes
            ctx.ctes = []
            try:
                plan = compile_select(rel.select, ctx, None)
            finally:
                ctx.ctes = saved
            if rel.cols:
                plan.names = list(rel.cols) + list(plan.names[len(rel.cols):])
            return plan_source(plan, alias or rel.name)
        t = rel
        src = Source(alias or t.name, [c.name for c in t.columns], [c.affinity for c in t.columns],
                     [c.collate for c in t.columns], table=t, has_rowid=True)
        src.rows_fn = lambda t=t: iter(t.scan().values()) if t.ordered or True else None
        for i, c in enumerate(t.columns):
            if c.hidden:
                src.hidden.add(i)
        return src

    # ---- joins: USING / NATURAL
    def prepare_joins(self):
        scope = self.scope
        for k, st in enumerate(self.steps):
            if k == 0:
                continue
            cols = None
            if st.natural:
                left_names = []
                for s in self.steps[:k]:
                    for i, c in enumerate(s.src.cols):
                        if i not in s.src.hidden:
                            left_names.append(c.lower())
                cols = [c for i, c in enumerate(st.src.cols) if c.lower() in left_names]
            elif st.using:
                cols = list(st.using)
            if cols is not None:
                conds = []
                for c in cols:
                    li = None
                    for s in self.steps[:k]:
                        for i, cn in enumerate(s.src.cols):
                            if cn.lower() == c.lower() and i not in s.src.hidden:
                                li = (s, i)
                                break
                        if li:
                            break
                    ri = None
                    for i, cn in enumerate(st.src.cols):
                        if cn.lower() == c.lower():
                            ri = i
                            break
                    if li is None or ri is None:
                        raise SqlError('cannot join using column %s - column not present in both tables' % c,
                                       'parse')
                    st.src.hidden.add(ri)
                    conds.append(('bin', '=', ('pos', li[0].src.offset + li[1]), ('pos', st.src.offset + ri)))
                node = None
                for cnd in conds:
                    node = cnd if node is None else ('bin', 'AND', node, cnd)
                if st.on is not None:
                    node = ('bin', 'AND', node, st.on)
                st.on = node

    # ---- planning
    def deps(self, node):
        acc = []
        walk_cols(node, acc)
        out = set()
        for c in acc:
            if c is None:
                return None
            if c[0] != 'col':
                continue
            if c[1] is not None and self.ctx.trigger_stack and c[1].lower() in ('new', 'old'):
                continue
            r = self.comp.try_resolve(c[1], c[2])
            if r is None:
                return None
            depth, pos, scope, si = r
            if depth == 0:
                out.add(si)
        # 'pos' nodes
        self._pos_deps(node, out)
        return out

    def _pos_deps(self, node, out):
        if isinstance(node, tuple):
            if node and node[0] == 'pos':
                s, i = self.scope.pos_info(node[1])
                out.add(self.scope.sources.index(s))
                return
            for x in node:
                self._pos_deps(x, out)
        elif isinstance(node, list):
            for x in node:
                self._pos_deps(x, out)

    def plan_where(self, where):
        conjs = split_and(where)
        n = len(self.steps)
        for st in self.steps:
            st.on_conjs = split_and(st.on) if st.on is not None else []
        # candidate extraction from ON clauses and WHERE
        for k, st in enumerate(self.steps):
            sources_conj = list(st.on_conjs)
            if not self.has_outer_right and (st.jtype in (None, 'INNER', 'CROSS') or k == 0):
                sources_conj += conjs
            for cj in sources_conj:
                self.try_candidate(k, st, cj)
        # pushdown of WHERE conjuncts
        self.final_where = []
        for cj in conjs:
            fn = self.comp.comp(cj)
            if self.has_outer_right:
                self.final_where.append(fn)
                continue
            d = self.deps(cj)
            level = n - 1 if d is None else (max(d) if d else 0)
            if level >= n:
                level = n - 1
            self.where_filters.append((level, fn))
        for st in self.steps:
            st.on_fn = self.comp.comp(st.on) if st.on is not None else None

    def try_candidate(self, k, st, cj):
        if cj[0] == 'paren':
            cj = cj[1]
        if cj[0] != 'bin' or cj[1] != '=':
            return
        for a, b in ((cj[2], cj[3]), (cj[3], cj[2])):
            while a[0] == 'paren':
                a = a[1]
            if a[0] not in ('col', 'pos'):
                continue
            if a[0] == 'col':
                r = self.comp.try_resolve(a[1], a[2])
                if r is None:
                    continue
                depth, pos, scope, si = r
                if depth != 0 or si != k:
                    continue
            else:
                s, i = self.scope.pos_info(a[1])
                if self.scope.sources.index(s) != k:
                    continue
                pos = a[1]
            d = self.deps(b)
            if d is None or any(x >= k for x in d):
                continue
            s, i = self.scope.pos_info(pos)
            aff_a = None if (i < 0) else s.affs[i]
            aff_a = 'INTEGER' if i < 0 else aff_a
            ca, cb = compare_convs(None if aff_a == 'BLOB' else aff_a, self.comp.aff_of(b))
            if ca is not None:
                continue
            cname = self.comp.pair_collation(a, b)
            colcoll = (s.colls[i].upper() if (i >= 0 and s.colls[i]) else None)
            if (cname or 'BINARY') != (colcoll or 'BINARY'):
                continue
            valfn = self.comp.comp(b)
            st.cands.append((i, valfn, cb, colcoll))
            return

    # ---- execution
    def iter(self):
        if self.empty:
            rows = iter([[]])
            for fn in self.empty_filters:
                rows = (r for r in rows if truth(fn(r)))
            return rows
        n = len(self.steps)
        cache = {}
        stream = iter([[]])
        for k, st in enumerate(self.steps):
            stream = self.join_level(stream, k, st, cache)
            for lvl, fn in self.where_filters:
                if lvl == k:
                    stream = self.filter_stream(stream, fn)
        for fn in self.final_where:
            stream = self.filter_stream(stream, fn)
        return stream

    @staticmethod
    def filter_stream(stream, fn):
        return (r for r in stream if truth(fn(r)))

    def source_rows(self, st, cache, k):
        rows = cache.get(k)
        if rows is None:
            rows = cache[k] = list(st.src.rows_fn())
        return rows

    def make_candidates(self, k, st, cache):
        """Returns function prefix -> iterable of right rows."""
        src = st.src
        t = src.table
        for (ci, valfn, conv, colcoll) in st.cands:
            if t is not None and ci < 0:
                rows = t.rows

                def by_rowid(prefix, valfn=valfn, conv=conv, rows=rows):
                    v = valfn(prefix)
                    if v is None:
                        return ()
                    if conv:
                        v = conv(v)
                    if type(v) is float and v.is_integer():
                        v = int(v)
                    row = rows.get(v) if type(v) is int else None
                    return () if row is None else (row,)
                return by_rowid
        if t is not None:
            colset = {}
            for (ci, valfn, conv, colcoll) in st.cands:
                colset.setdefault(ci, (valfn, conv))
            best = None
            for ix in t.indexes:
                if ix.colidx is None or ix.pred is not None:
                    continue
                if all(c in colset for c in ix.colidx):
                    # collation of index key must match
                    if best is None or (ix.unique and not best.unique) or len(ix.colidx) > len(best.colidx):
                        best = ix
            if best is not None:
                ix = best
                parts = [colset[c] for c in ix.colidx]
                rows = t.rows

                def by_index(prefix, ix=ix, parts=parts, rows=rows):
                    vals = []
                    for valfn, conv in parts:
                        v = valfn(prefix)
                        if v is None:
                            return ()
                        if conv:
                            v = conv(v)
                        vals.append(v)
                    return [rows[rid] for rid in ix.rowids(ix.lookup_key(vals))]
                return by_index
        if (k > 0 or (t is not None and not t.virtual)) and st.cands:
            ci, valfn, conv, colcoll = st.cands[0]
            ck = get_collation(colcoll) if colcoll else None
            keyf = (lambda v: ck(v) if (ck and type(v) is str) else v)
            if ci < 0:
                ci = len(src.cols)
            holder = st.__dict__.setdefault('holder', {})

            def by_hash(prefix):
                h = holder.get('h')
                stamp = t.version if t is not None else cache
                if h is None or holder.get('gen') is not stamp:
                    h = {}
                    rows_iter = list(t.scan().values()) if t is not None else self.source_rows(st, cache, k)
                    for rr in rows_iter:
                        v = rr[ci]
                        if v is None:
                            continue
                        h.setdefault(keyf(v), []).append(rr)
                    holder['h'] = h
                    holder['gen'] = stamp
                v = valfn(prefix)
                if v is None:
                    return ()
                if conv:
                    v = conv(v)
                return h.get(keyf(v), ())
            return by_hash
        if k > 0:
            return lambda prefix: self.source_rows(st, cache, k)
        return lambda prefix: st.src.rows_fn()

    def join_level(self, stream, k, st, cache):
        on = st.on_fn
        jt = st.jtype
        src = st.src
        width = src.width
        if jt in ('RIGHT', 'FULL'):
            return self.join_outer_right(stream, k, st, cache)
        cands = self.make_candidates(k, st, cache)
        nulls = [None] * width
        left = jt == 'LEFT'
        if k == 0:
            def gen0():
                for rr in cands([]):
                    if on is None or truth(on(rr)):
                        yield rr
            return gen0()

        def gen():
            for l in stream:
                m = False
                for rr in cands(l):
                    row = l + rr
                    if on is None or truth(on(row)):
                        m = True
                        yield row
                if left and not m:
                    yield l + nulls
        return gen()

    def join_outer_right(self, stream, k, st, cache):
        on = st.on_fn
        full = st.jtype == 'FULL'
        src = st.src
        width = src.width
        offset = src.offset

        def gen():
            lefts = list(stream)
            rrows = self.source_rows(st, cache, k)
            matched = [False] * len(rrows)
            nulls = [None] * width
            for l in lefts:
                m = False
                for i, rr in enumerate(rrows):
                    row = l + rr
                    if on is None or truth(on(row)):
                        matched[i] = True
                        m = True
                        yield row
                if full and not m:
                    yield l + nulls
            lnull = [None] * offset
            for i, rr in enumerate(rrows):
                if not matched[i]:
                    yield lnull + rr
        return gen()


# ---------------------------------------------------------------------- core select
def star_items(scope, table):
    items = []
    found = False
    for s in scope.sources:
        if table is not None and (s.alias or '').lower() != table.lower():
            continue
        found = True
        for i, c in enumerate(s.cols):
            if i in s.hidden:
                continue
            items.append((('pos', s.offset + i), c))
    if not found and table is not None:
        raise SqlError('no such table: %s' % table, 'parse')
    return items


class CorePlan(BasePlan):
    def __init__(self, core, sel, ctx, parent_scope):
        self.ctx = ctx
        self.scope = scope = Scope(parent_scope)
        for c in core['cols']:
            if c[0] == 'expr' and c[2] is not None:
                scope.aliases.setdefault(c[2].lower(), c[1])
        self.from_plan = FromPlan(ctx, scope, core['from'], core['where'])
        self.distinct = core['distinct']
        self.setup_limits(sel, ctx, parent_scope)
        # --- result columns
        outcols = []
        for c in core['cols']:
            if c[0] == 'star':
                if core['from'] is None:
                    raise SqlError('no tables specified', 'parse')
                outcols.extend(star_items(scope, c[1]))
            else:
                _, e, alias, text = c
                if alias is not None:
                    name = alias
                elif e[0] == 'col':
                    name = e[2]
                else:
                    name = text
                outcols.append((e, name))
        self.names = [n for _, n in outcols]
        for e, name in outcols:
            pass
        # aliases usable in WHERE / GROUP BY / HAVING
        for c in core['cols']:
            if c[0] == 'expr' and c[2] is not None:
                scope.aliases.setdefault(c[2].lower(), c[1])
        self.aggs = []
        wins = None
        if any(has_window(e) for e, _ in outcols) or has_window(core['having']) or \
                (sel.get('order') and any(has_window(o[0]) for o in sel['order'])):
            from .windows import WindowCollector
            wins = WindowCollector(core.get('windows'))
        comp = Comp(ctx, scope, self.aggs, wins)
        self.out_fns = [comp.comp(e) for e, _ in outcols]
        self.out_affs = [comp.aff_of(e) for e, _ in outcols]
        self.out_asts = [e for e, _ in outcols]
        # where already compiled in FromPlan (with aggregates disallowed)
        self.group_fns = None
        self.group_cks = None
        if core['group']:
            gfs = []
            gcks = []
            for g in core['group']:
                if g[0] == 'lit' and type(g[1]) is int:
                    if not 1 <= g[1] <= len(outcols):
                        raise SqlError('%s GROUP BY term out of range' % _ordinal(g[1]), 'parse')
                    g = outcols[g[1] - 1][0]
                if has_agg_or_window(g):
                    raise SqlError('aggregate functions are not allowed in the GROUP BY clause', 'parse')
                gc = Comp(ctx, scope, None)
                gfs.append(gc.comp(g))
                cn = gc.coll_of(g)[0]
                gcks.append(get_collation(cn) if cn else None)
            self.group_fns = gfs
            self.group_cks = gcks
        self.having_fn = None
        if core['having'] is not None:
            self.having_fn = comp.comp(core['having'])
        # --- ORDER BY
        self.order_terms = []
        if sel.get('order'):
            for e, desc, nulls in sel['order']:
                ck = None
                explicit = False
                ee = e
                while ee[0] in ('collate', 'paren'):
                    if ee[0] == 'collate' and not explicit:
                        ck = get_collation(ee[2])
                        explicit = True
                    ee = ee[1]
                nf = (nulls == 'FIRST') if nulls else None
                if ee[0] == 'lit' and type(ee[1]) is int:
                    if not 1 <= ee[1] <= len(outcols):
                        raise SqlError('%s ORDER BY term out of range - should be between 1 and %d'
                                       % (_ordinal(ee[1]), len(outcols)), 'parse')
                    idx = ee[1] - 1
                    if not explicit:
                        cn = comp.coll_of(outcols[idx][0])[0]
                        ck = get_collation(cn) if cn else None
                    self.order_terms.append(('out', idx, desc, nf, ck))
                    continue
                if ee[0] == 'col' and ee[1] is None:
                    lname = ee[2].lower()
                    hit = None
                    for i, c in enumerate(core['cols']):
                        pass
                    for i, (oe, nm) in enumerate(outcols):
                        if nm.lower() == lname:
                            hit = i
                            break
                    if hit is not None:
                        if not explicit:
                            cn = comp.coll_of(outcols[hit][0])[0]
                            ck = get_collation(cn) if cn else None
                        self.order_terms.append(('out', hit, desc, nf, ck))
                        continue
                if not explicit:
                    cn = comp.coll_of(ee)[0]
                    ck = get_collation(cn) if cn else None
                self.order_terms.append(('expr', comp.comp(ee), desc, nf, ck))
        self.wins = wins
        self.aggregated = bool(self.aggs) or core['group'] is not None
        if wins is not None:
            if self.aggregated:
                pass
            wins.finish(self)
        self.stop_after = None

    @property
    def correlated(self):
        return self.scope.correlated

    # ------------------------------------------------------------ execution
    def iter(self):
        lim, off = self.limits()
        if self.limit_hint is not None and not self.order_terms and not self.aggregated:
            lim = self.limit_hint if lim is None else min(lim, self.limit_hint)
        rows = self.from_plan.iter()
        if self.wins is not None and not self.aggregated:
            rows = self.wins.apply(list(rows))
        out_fns = self.out_fns
        order_terms = self.order_terms
        if self.aggregated:
            return self.finish(self.run_grouped(rows), lim, off)
        if not order_terms:
            return self.stream(rows, lim, off)
        items = []
        for r in rows:
            out = tuple([f(r) for f in out_fns])
            items.append((out, [out[t[1]] if t[0] == 'out' else t[1](r) for t in order_terms]))
        return self.finish(items, lim, off)

    def stream(self, rows, lim, off):
        out_fns = self.out_fns
        distinct = self.distinct
        seen = set() if distinct else None
        skipped = 0
        produced = 0
        if lim == 0:
            return
        for r in rows:
            out = tuple([f(r) for f in out_fns])
            if distinct:
                if out in seen:
                    continue
                seen.add(out)
            if off and skipped < off:
                skipped += 1
                continue
            yield out
            produced += 1
            if lim is not None and produced >= lim:
                return

    def finish(self, items, lim, off):
        order_terms = self.order_terms
        if self.distinct:
            seen = set()
            ded = []
            for it in items:
                if it[0] in seen:
                    continue
                seen.add(it[0])
                ded.append(it)
            items = ded
        if order_terms:
            sort_rows(items, [(t[2], t[3], t[4]) for t in order_terms])
        rows = [i[0] for i in items]
        if off:
            rows = rows[off:]
        if lim is not None:
            rows = rows[:lim]
        return iter(rows)

    def run_grouped(self, rows):
        aggs = self.aggs
        group_fns = self.group_fns
        gcks = self.group_cks
        width = self.scope.width
        single_minmax = len(aggs) == 1 and aggs[0][5] in ('min', 'max')
        groups = {}
        for r in rows:
            if group_fns is not None:
                key = tuple([(gcks[i](v) if (gcks[i] and type(v) is str) else v)
                             for i, v in enumerate([g(r) for g in group_fns])])
            else:
                key = ()
            g = groups.get(key)
            if g is None:
                g = groups[key] = [r, [make_acc(a) for a in aggs], [set() if a[2] else None for a in aggs], key]
            elif not single_minmax:
                g[0] = r
            accs = g[1]
            for i, a in enumerate(aggs):
                cls, argfs, distinct, flf, ck, name = a
                if flf is not None and not truth(flf(r)):
                    continue
                if argfs:
                    vals = [f(r) for f in argfs]
                    if distinct:
                        if vals[0] is None or vals[0] in g[2][i]:
                            continue
                        g[2][i].add(vals[0])
                    res = accs[i].step(*vals)
                    if single_minmax and res:
                        g[0] = r
                else:
                    accs[i].step()
        if group_fns is None and not groups:
            groups[()] = [[None] * width, [make_acc(a) for a in aggs], [None] * len(aggs), ()]
        glist = list(groups.values())
        if group_fns is not None:
            glist.sort(key=lambda g: tuple([sortkey(v, gcks[i]) for i, v in enumerate(g[3])]))
        out_fns = self.out_fns
        order_terms = self.order_terms
        having = self.having_fn
        grows = []
        for g in glist:
            grow = g[0] + [acc.final() for acc in g[1]]
            if having is not None and not truth(having(grow)):
                continue
            grows.append(grow)
        if self.wins is not None:
            grows = self.wins.apply(grows)
        items = []
        for grow in grows:
            out = tuple([f(grow) for f in out_fns])
            items.append((out, [out[t[1]] if t[0] == 'out' else t[1](grow) for t in order_terms]))
        return items


def make_acc(a):
    cls, argfs, distinct, flf, ck, name = a
    if name in ('min', 'max'):
        return cls(ck)
    return cls()


def has_window(node):
    if isinstance(node, tuple):
        if node and node[0] == 'func' and node[6] is not None:
            return True
        if node and node[0] in ('subq', 'exists'):
            return False
        return any(has_window(x) for x in node)
    if isinstance(node, list):
        return any(has_window(x) for x in node)
    return False
