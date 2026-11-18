"""Window function evaluation (OVER clauses)."""
from .errors import SqlError
from . import functions as F
from .values import sortkey, get_collation, truth, compare, to_numeric
from .query import sort_rows

RANKING = {'row_number', 'rank', 'dense_rank', 'percent_rank', 'cume_dist', 'ntile'}
VALUE_FUNCS = {'lag', 'lead', 'first_value', 'last_value', 'nth_value'}
ARITY = {'row_number': (0, 0), 'rank': (0, 0), 'dense_rank': (0, 0), 'percent_rank': (0, 0),
         'cume_dist': (0, 0), 'ntile': (1, 1), 'lag': (1, 3), 'lead': (1, 3), 'first_value': (1, 1),
         'last_value': (1, 1), 'nth_value': (2, 2)}


class Spec:
    def __init__(self, part, order, frame):
        self.part = part          # list of fns
        self.order = order        # list of (fn, desc, nulls_first, ck)
        self.frame = frame        # (unit, start, end, excl) with compiled offsets, or None


class WinFunc:
    def __init__(self, name, kind, args, flt, spec, key, cls=None, ck=None):
        self.name = name
        self.kind = kind
        self.args = args
        self.flt = flt
        self.spec = spec
        self.key = key
        self.cls = cls
        self.ck = ck


class WindowCollector:
    def __init__(self, named):
        self.named = named or {}
        self.funcs = []
        self.holder = [0]

    def resolve(self, over, seen=()):
        _, base, part, order, frame = over
        if base is None:
            return part, order, frame
        if base in seen or base not in self.named:
            raise SqlError('no such window: %s' % base, 'parse')
        bp, bo, bf = self.resolve(self.named[base], seen + (base,))
        if part is not None and bp is not None:
            raise SqlError('PARTITION clause not allowed in derived window definition', 'parse')
        if order is not None and bo is not None:
            raise SqlError('ORDER BY clause not allowed in derived window definition', 'parse')
        return (part if part is not None else bp, order if order is not None else bo,
                frame if frame is not None else bf)

    def register(self, comp, node):
        _, name, args, distinct, star, flt, over = node
        n = len(args)
        part, order, frame = self.resolve(over)
        is_agg = name in F.AGGREGATES and not (name in ('min', 'max') and n != 1)
        if not is_agg and name not in ARITY:
            if name in F.SCALARS or name in F.SPECIAL:
                raise SqlError('%s() may not be used as a window function' % name, 'parse')
            raise SqlError('no such function: %s' % name, 'parse')
        if name in ARITY:
            lo, hi = ARITY[name]
            if n < lo or n > hi:
                raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
        if distinct:
            raise SqlError('DISTINCT is not supported for window functions', 'parse')
        saved = comp.in_agg
        pf = [comp.comp(e) for e in (part or [])]
        of = []
        for e, desc, nulls in (order or []):
            ee = e
            ck = None
            explicit = False
            while ee[0] in ('collate', 'paren'):
                if ee[0] == 'collate' and not explicit:
                    ck = get_collation(ee[2])
                    explicit = True
                ee = ee[1]
            if not explicit:
                cn = comp.coll_of(ee)[0]
                ck = get_collation(cn) if cn else None
            of.append((comp.comp(ee), desc, (nulls == 'FIRST') if nulls else None, ck))
        fr = None
        if frame is not None:
            unit, start, end, excl = frame
            fr = (unit, self.comp_bound(comp, start), self.comp_bound(comp, end), excl)
            self.check_frame(fr)
        spec = Spec(pf, of, fr)
        key = repr((part, order, frame))
        argfs = [comp.comp(a) for a in args]
        flf = comp.comp(flt) if flt is not None else None
        cls = None
        ck = None
        if is_agg and name not in ARITY:
            kind = 'agg'
            cls = F.AggCountStar if (name == 'count' and star) else F.AGGREGATES[name]
            if name in ('min', 'max'):
                cn = comp.coll_of(args[0])[0]
                ck = get_collation(cn) if cn else None
            if name in ('group_concat', 'string_agg') and n not in (1, 2):
                raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
            if name not in ('count', 'group_concat', 'string_agg') and (n != 1 or star):
                raise SqlError('wrong number of arguments to function %s()' % name, 'parse')
        elif name in RANKING:
            kind = 'rank'
        else:
            kind = 'value'
        k = len(self.funcs)
        self.funcs.append(WinFunc(name, kind, argfs, flf, spec, key, cls, ck))
        holder = self.holder
        return lambda r: r[holder[0] + k]

    @staticmethod
    def comp_bound(comp, b):
        if b[0] == 'offset':
            return ('offset', comp.comp(b[1]), b[2])
        return b

    @staticmethod
    def check_frame(fr):
        unit, start, end, excl = fr
        if start == ('unbounded', 'FOLLOWING'):
            raise SqlError('unsupported frame specification', 'parse')
        if end == ('unbounded', 'PRECEDING'):
            raise SqlError('unsupported frame specification', 'parse')

    def finish(self, plan):
        self.holder[0] = plan.scope.width + len(plan.aggs)

    # ------------------------------------------------------------ evaluation
    def process(self, plan, rows):
        rows = [list(r) + [None] * len(plan.aggs) for r in rows] if plan.aggs else list(rows)
        if plan.aggregated:
            return rows
        return self.apply(rows)

    def apply(self, rows):
        nf = len(self.funcs)
        results = [[None] * nf for _ in rows]
        groups = {}
        for fi, f in enumerate(self.funcs):
            groups.setdefault(f.key, (f.spec, []))[1].append(fi)
        order = None
        for si, (spec, fidx) in enumerate(groups.values()):
            parts = {}
            for ri, r in enumerate(rows):
                key = tuple([pf(r) for pf in spec.part])
                parts.setdefault(key, []).append(ri)
            pkeys = sorted(parts, key=lambda k: tuple([sortkey(v) for v in k]))
            arranged = []
            for key in pkeys:
                idxs = parts[key]
                if spec.order:
                    items = [(ri, [of[0](rows[ri]) for of in spec.order]) for ri in idxs]
                    sort_rows(items, [(of[1], of[2], of[3]) for of in spec.order])
                    idxs = [i[0] for i in items]
                arranged.append(idxs)
                self.partition(rows, idxs, spec, fidx, results)
            if si == 0:
                order = [ri for idxs in arranged for ri in idxs]
        if order is None:
            order = range(len(rows))
        return [rows[ri] + results[ri] for ri in order]

    def partition(self, rows, idxs, spec, fidx, results):
        N = len(idxs)
        prow = [rows[i] for i in idxs]
        okeys = [tuple([sortkey(of[0](r), of[3]) for of in spec.order]) for r in prow]
        gid = [0] * N
        gstart = []
        gend = []
        g = -1
        for i in range(N):
            if i == 0 or okeys[i] != okeys[i - 1]:
                g += 1
                gstart.append(i)
                gend.append(i)
            gend[g] = i
            gid[i] = g
        ng = g + 1
        ctx = (N, gid, gstart, gend, ng, spec, prow)
        for fi in fidx:
            f = self.funcs[fi]
            vals = self.eval_func(f, ctx)
            for i in range(N):
                results[idxs[i]][fi] = vals[i]

    def frame_of(self, spec, ctx, i):
        """Return (start, end) inclusive row indexes of the frame for row i, or None if empty."""
        N, gid, gstart, gend, ng, _, prow = ctx
        if spec.frame is None:
            unit, start, end = 'RANGE', ('unbounded', 'PRECEDING'), ('current',)
        else:
            unit, start, end, _e = spec.frame
        g = gid[i]
        if unit == 'ROWS':
            s = self.rows_bound(start, i, 0, N, True)
            e = self.rows_bound(end, i, N - 1, N, False)
        elif unit == 'GROUPS':
            sg = self.rows_bound(start, g, 0, ng, True)
            eg = self.rows_bound(end, g, ng - 1, ng, False)
            if sg is None or eg is None or sg > eg:
                return None
            s = gstart[max(sg, 0)] if sg < ng else None
            e = gend[min(eg, ng - 1)] if eg >= 0 else None
        else:
            s = self.range_bound(spec, ctx, start, i, True)
            e = self.range_bound(spec, ctx, end, i, False)
        if s is None or e is None:
            return None
        s = max(s, 0)
        e = min(e, N - 1)
        if s > e:
            return None
        return s, e

    @staticmethod
    def offset_value(b):
        v = b[1]([])
        v = to_numeric(v) if v is not None else None
        if v is None or v < 0:
            raise SqlError('frame starting offset must be a non-negative integer' if False else
                           'frame offset must be a non-negative number')
        return v

    def rows_bound(self, b, i, edge, N, is_start):
        if b[0] == 'unbounded':
            return 0 if b[1] == 'PRECEDING' else N - 1
        if b[0] == 'current':
            return i
        k = int(self.offset_value(b))
        return i - k if b[2] == 'PRECEDING' else i + k

    def range_bound(self, spec, ctx, b, i, is_start):
        N, gid, gstart, gend, ng, _, prow = ctx
        g = gid[i]
        if b[0] == 'unbounded':
            return 0 if b[1] == 'PRECEDING' else N - 1
        if b[0] == 'current':
            return gstart[g] if is_start else gend[g]
        if len(spec.order) != 1:
            raise SqlError('RANGE with offset PRECEDING/FOLLOWING requires exactly one ORDER BY term')
        fn, desc, nf, ck = spec.order[0]
        v = fn(prow[i])
        if v is None:
            return gstart[g] if is_start else gend[g]
        k = self.offset_value(b)
        v = to_numeric(v)
        pre = b[2] == 'PRECEDING'
        target = v - k if (pre != desc) else v + k
        keys = [fn(r) for r in prow]
        # asc: rows with key in [lo, hi]; desc mirrors
        if not desc:
            if is_start:
                for j in range(N):
                    kv = keys[j]
                    if kv is not None and to_numeric(kv) >= target:
                        return j
                return None
            last = None
            for j in range(N):
                kv = keys[j]
                if kv is not None and to_numeric(kv) <= target:
                    last = j
            return last
        if is_start:
            for j in range(N):
                kv = keys[j]
                if kv is not None and to_numeric(kv) <= target:
                    return j
            return None
        last = None
        for j in range(N):
            kv = keys[j]
            if kv is not None and to_numeric(kv) >= target:
                last = j
        return last

    def frame_indexes(self, spec, ctx, i, fr):
        if fr is None:
            return []
        s, e = fr
        excl = spec.frame[3] if spec.frame else None
        N, gid, gstart, gend, ng, _, prow = ctx
        idx = range(s, e + 1)
        if excl is None or excl == 'NO OTHERS':
            return idx
        g = gid[i]
        if excl == 'CURRENT ROW':
            return [j for j in idx if j != i]
        if excl == 'GROUP':
            return [j for j in idx if gid[j] != g]
        return [j for j in idx if gid[j] != g or j == i]   # TIES

    def eval_func(self, f, ctx):
        N, gid, gstart, gend, ng, spec, prow = ctx
        name = f.name
        out = [None] * N
        if f.kind == 'rank':
            if name == 'row_number':
                return list(range(1, N + 1))
            if name == 'rank':
                return [gstart[gid[i]] + 1 for i in range(N)]
            if name == 'dense_rank':
                return [gid[i] + 1 for i in range(N)]
            if name == 'percent_rank':
                return [0.0 if N == 1 else float(gstart[gid[i]]) / (N - 1) for i in range(N)]
            if name == 'cume_dist':
                return [float(gend[gid[i]] + 1) / N for i in range(N)]
            nt = f.args[0](prow[0]) if N else 1
            nt = to_numeric(nt) if nt is not None else 0
            if nt is None or int(nt) <= 0:
                raise SqlError('argument of ntile must be a positive integer')
            nt = int(nt)
            size, rem = divmod(N, nt)
            res = []
            b = 0
            while len(res) < N:
                cnt = size + (1 if b < rem else 0)
                if cnt == 0:
                    break
                res.extend([b + 1] * cnt)
                b += 1
            return res[:N]
        if f.kind == 'value':
            if name in ('lag', 'lead'):
                for i in range(N):
                    r = prow[i]
                    off = 1
                    if len(f.args) > 1:
                        off = f.args[1](r)
                        off = to_numeric(off) if off is not None else None
                        if off is None or int(off) < 0:
                            raise SqlError('second argument to %s() must be a non-negative integer' % name
                                           if False else 'argument of %s must be a non-negative integer' % name)
                        off = int(off)
                    j = i - off if name == 'lag' else i + off
                    if 0 <= j < N:
                        out[i] = f.args[0](prow[j])
                    elif len(f.args) > 2:
                        out[i] = f.args[2](r)
                return out
            nth = None
            for i in range(N):
                fr = self.frame_of(spec, ctx, i)
                idx = self.frame_indexes(spec, ctx, i, fr)
                if not len(idx):
                    continue
                if name == 'first_value':
                    out[i] = f.args[0](prow[idx[0]])
                elif name == 'last_value':
                    out[i] = f.args[0](prow[idx[-1]])
                else:
                    n = f.args[1](prow[i])
                    n = to_numeric(n) if n is not None else None
                    if n is None or int(n) <= 0:
                        raise SqlError('second argument to nth_value must be a positive integer')
                    n = int(n)
                    if n <= len(idx):
                        out[i] = f.args[0](prow[idx[n - 1]])
            return out
        # aggregate over frame
        cls = f.cls
        mk = (lambda: cls(f.ck)) if f.name in ('min', 'max') else (lambda: cls())

        def feed(acc, r):
            if f.flt is not None and not truth(f.flt(r)):
                return
            if f.args:
                acc.step(*[a(r) for a in f.args])
            else:
                acc.step()
        excl = spec.frame[3] if spec.frame else None
        if excl in (None, 'NO OTHERS'):
            acc = mk()
            added = 0      # rows [0, added) have been fed (valid while the frame starts at row 0)
            for i in range(N):
                fr = self.frame_of(spec, ctx, i)
                if fr is None:
                    out[i] = mk().final()
                    continue
                s, e = fr
                if s == 0 and added <= e + 1 and self._starts_at_zero(spec):
                    while added <= e:
                        feed(acc, prow[added])
                        added += 1
                    if added == e + 1:
                        out[i] = acc.final()
                        continue
                a2 = mk()
                for j in range(s, e + 1):
                    feed(a2, prow[j])
                out[i] = a2.final()
            return out
        for i in range(N):
            fr = self.frame_of(spec, ctx, i)
            a2 = mk()
            for j in self.frame_indexes(spec, ctx, i, fr):
                feed(a2, prow[j])
            out[i] = a2.final()
        return out

    @staticmethod
    def _starts_at_zero(spec):
        if spec.frame is None:
            return True
        return spec.frame[1] == ('unbounded', 'PRECEDING')
