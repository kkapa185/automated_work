"""Recursive-descent SQL parser producing tuple/dict ASTs.

Expressions are tuples whose first element is a tag; statements are dicts.
"""
from .errors import SqlError, parse_error
from .tokenizer import tokenize
from .values import INT_MAX, INT_MIN

RESERVED = set('''ALL AND AS BETWEEN CASE CHECK COLLATE COMMIT CONSTRAINT CREATE CROSS DEFAULT DEFERRABLE
DELETE DISTINCT DROP ELSE ESCAPE EXCEPT EXISTS FOREIGN FROM FULL GLOB GROUP HAVING IN INDEX INNER INSERT
INTERSECT INTO IS ISNULL JOIN LEFT LIKE LIMIT NATURAL NOT NOTNULL NULL ON OR ORDER OUTER PRIMARY
REFERENCES RIGHT SELECT SET TABLE THEN TO UNION UNIQUE UPDATE USING VALUES WHEN WHERE WINDOW RETURNING'''.split())

COLUMN_CONSTRAINT_WORDS = {'CONSTRAINT', 'PRIMARY', 'NOT', 'NULL', 'UNIQUE', 'CHECK', 'DEFAULT', 'COLLATE',
                           'REFERENCES', 'GENERATED', 'AS'}


class Parser:
    def __init__(self, src):
        self.src = src
        self.toks = tokenize(src)
        self.i = 0

    # ------------------------------------------------------------ token helpers
    @property
    def tok(self):
        return self.toks[self.i]

    def peek(self, k=1):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else self.toks[-1]

    def next(self):
        t = self.toks[self.i]
        if t.kind != 'eof':
            self.i += 1
        return t

    @property
    def prev_end(self):
        return self.toks[self.i - 1].end if self.i > 0 else 0

    def error(self, tok=None):
        t = tok or self.tok
        if t.kind == 'eof':
            return parse_error('incomplete input')
        if t.kind == 'bad':
            return parse_error('unrecognized token: "%s"' % t.val)
        return parse_error('near "%s": syntax error' % self.src[t.start:t.end])

    def is_kw(self, *kws):
        t = self.tok
        return t.kind == 'id' and t.up in kws

    def accept_kw(self, *kws):
        t = self.tok
        if t.kind == 'id' and t.up in kws:
            self.i += 1
            return t.up
        return None

    def expect_kw(self, kw):
        if not self.accept_kw(kw):
            raise self.error()

    def is_op(self, op):
        t = self.tok
        return t.kind == 'op' and t.val == op

    def accept_op(self, op):
        t = self.tok
        if t.kind == 'op' and t.val == op:
            self.i += 1
            return True
        return False

    def expect_op(self, op):
        if not self.accept_op(op):
            raise self.error()

    def ident(self):
        t = self.tok
        if t.kind == 'qid' or t.kind == 'str':
            self.i += 1
            return t.val
        if t.kind == 'id' and t.up not in RESERVED:
            self.i += 1
            return t.val
        raise self.error()

    def accept_ident(self):
        t = self.tok
        if t.kind == 'qid' or (t.kind == 'id' and t.up not in RESERVED):
            self.i += 1
            return t.val
        return None

    def qualified_name(self):
        """[schema.]name -> name (schema ignored)."""
        n = self.ident()
        if self.accept_op('.'):
            n = self.ident()
        return n

    # ------------------------------------------------------------ statements
    def at_end(self):
        return self.tok.kind == 'eof'

    def parse_statement(self):
        """Parse one statement (without trailing ';'). Returns dict or None for empty."""
        while self.accept_op(';'):
            pass
        if self.at_end():
            return None
        t = self.tok
        start = t.start
        if t.kind == 'bad':
            raise self.error()
        if t.kind != 'id':
            raise self.error()
        kw = t.up
        if kw == 'EXPLAIN':
            raise parse_error('EXPLAIN is not supported')
        if kw in ('SELECT', 'VALUES', 'WITH'):
            stmt = self.parse_with_stmt()
        elif kw in ('INSERT', 'REPLACE'):
            stmt = self.parse_insert(None)
        elif kw == 'UPDATE':
            stmt = self.parse_update(None)
        elif kw == 'DELETE':
            stmt = self.parse_delete(None)
        elif kw == 'CREATE':
            stmt = self.parse_create()
        elif kw == 'DROP':
            stmt = self.parse_drop()
        elif kw == 'ALTER':
            stmt = self.parse_alter()
        elif kw == 'BEGIN':
            self.next()
            mode = self.accept_kw('DEFERRED', 'IMMEDIATE', 'EXCLUSIVE') or 'DEFERRED'
            self.accept_kw('TRANSACTION')
            stmt = {'type': 'begin', 'mode': mode}
        elif kw in ('COMMIT', 'END'):
            self.next()
            self.accept_kw('TRANSACTION')
            stmt = {'type': 'commit'}
        elif kw == 'ROLLBACK':
            self.next()
            self.accept_kw('TRANSACTION')
            name = None
            if self.accept_kw('TO'):
                self.accept_kw('SAVEPOINT')
                name = self.ident()
            stmt = {'type': 'rollback', 'to': name}
        elif kw == 'SAVEPOINT':
            self.next()
            stmt = {'type': 'savepoint', 'name': self.ident()}
        elif kw == 'RELEASE':
            self.next()
            self.accept_kw('SAVEPOINT')
            stmt = {'type': 'release', 'name': self.ident()}
        elif kw == 'PRAGMA':
            stmt = self.parse_pragma()
        elif kw in ('VACUUM', 'ANALYZE', 'REINDEX'):
            self.next()
            while not (self.at_end() or self.is_op(';')):
                self.next()
            stmt = {'type': 'noop'}
        else:
            raise self.error()
        if not (self.at_end() or self.is_op(';')):
            raise self.error()
        stmt['sql'] = self.src[start:self.prev_end]
        return stmt

    def parse_pragma(self):
        self.next()
        name = self.qualified_name()
        arg = None
        if self.accept_op('='):
            arg = self.pragma_value()
        elif self.accept_op('('):
            arg = self.pragma_value()
            self.expect_op(')')
        return {'type': 'pragma', 'name': name.lower(), 'arg': arg}

    def pragma_value(self):
        neg = self.accept_op('-')
        t = self.next()
        if t.kind in ('int', 'float'):
            return -t.val if neg else t.val
        if t.kind in ('id', 'str', 'qid'):
            return t.val
        raise self.error(t)

    def parse_with_stmt(self):
        w = None
        if self.is_kw('WITH'):
            w = self.parse_with_clause()
            kw = self.tok.up if self.tok.kind == 'id' else None
            if kw in ('INSERT', 'REPLACE'):
                return self.parse_insert(w)
            if kw == 'UPDATE':
                return self.parse_update(w)
            if kw == 'DELETE':
                return self.parse_delete(w)
        return self.parse_select(w)

    def parse_with_clause(self):
        self.expect_kw('WITH')
        rec = bool(self.accept_kw('RECURSIVE'))
        ctes = []
        while True:
            name = self.ident()
            cols = None
            if self.accept_op('('):
                cols = [self.ident()]
                while self.accept_op(','):
                    cols.append(self.ident())
                self.expect_op(')')
            self.expect_kw('AS')
            if self.accept_kw('NOT'):
                self.expect_kw('MATERIALIZED')
            else:
                self.accept_kw('MATERIALIZED')
            self.expect_op('(')
            sel = self.parse_select()
            self.expect_op(')')
            ctes.append((name, cols, sel))
            if not self.accept_op(','):
                break
        return (rec, ctes)

    # ------------------------------------------------------------ SELECT
    def parse_select(self, with_clause=None):
        if with_clause is None and self.is_kw('WITH'):
            with_clause = self.parse_with_clause()
        body = self.parse_select_core()
        while True:
            op = self.accept_kw('UNION', 'INTERSECT', 'EXCEPT')
            if not op:
                break
            if op == 'UNION' and self.accept_kw('ALL'):
                op = 'UNION ALL'
            right = self.parse_select_core()
            body = {'kind': 'compound', 'op': op, 'left': body, 'right': right}
        order = None
        limit = offset = None
        if self.accept_kw('ORDER'):
            self.expect_kw('BY')
            order = self.parse_order_terms()
        if self.accept_kw('LIMIT'):
            limit = self.parse_expr()
            if self.accept_kw('OFFSET'):
                offset = self.parse_expr()
            elif self.accept_op(','):
                offset = limit
                limit = self.parse_expr()
        return {'type': 'select', 'with': with_clause, 'body': body, 'order': order,
                'limit': limit, 'offset': offset}

    def parse_order_terms(self):
        terms = []
        while True:
            e = self.parse_expr()
            desc = False
            if self.accept_kw('ASC'):
                pass
            elif self.accept_kw('DESC'):
                desc = True
            nulls = None
            if self.accept_kw('NULLS'):
                k = self.accept_kw('FIRST', 'LAST')
                if not k:
                    raise self.error()
                nulls = k
            terms.append((e, desc, nulls))
            if not self.accept_op(','):
                break
        return terms

    def parse_select_core(self):
        if self.accept_kw('VALUES'):
            rows = []
            while True:
                self.expect_op('(')
                rows.append(self.parse_expr_list())
                self.expect_op(')')
                if not self.accept_op(','):
                    break
            return {'kind': 'values', 'rows': rows}
        if self.is_op('('):
            # parenthesised select inside a compound is not legal SQLite; treat as error
            raise self.error()
        self.expect_kw('SELECT')
        distinct = False
        if self.accept_kw('DISTINCT'):
            distinct = True
        else:
            self.accept_kw('ALL')
        cols = []
        while True:
            cols.append(self.parse_result_col())
            if not self.accept_op(','):
                break
        frm = where = having = None
        group = None
        windows = None
        if self.accept_kw('FROM'):
            frm = self.parse_from()
        if self.accept_kw('WHERE'):
            where = self.parse_expr()
        if self.accept_kw('GROUP'):
            self.expect_kw('BY')
            group = self.parse_expr_list()
            if self.accept_kw('HAVING'):
                having = self.parse_expr()
        elif self.accept_kw('HAVING'):
            having = self.parse_expr()
        if self.accept_kw('WINDOW'):
            windows = {}
            while True:
                name = self.ident()
                self.expect_kw('AS')
                windows[name.lower()] = self.parse_window_spec()
                if not self.accept_op(','):
                    break
        return {'kind': 'core', 'distinct': distinct, 'cols': cols, 'from': frm, 'where': where,
                'group': group, 'having': having, 'windows': windows}

    def parse_result_col(self):
        if self.is_op('*'):
            self.next()
            return ('star', None)
        t = self.tok
        if t.kind in ('id', 'qid', 'str') and self.peek().kind == 'op' and self.peek().val == '.' \
                and self.peek(2).kind == 'op' and self.peek(2).val == '*' and not (t.kind == 'id' and t.up in RESERVED):
            self.i += 3
            return ('star', t.val)
        start = t.start
        e = self.parse_expr()
        text = self.src[start:self.prev_end]
        alias = None
        if self.accept_kw('AS'):
            alias = self.ident()
        else:
            alias = self.accept_ident()
            if alias is None and self.tok.kind == 'str':
                alias = self.next().val
        return ('expr', e, alias, text)

    def parse_from(self):
        left = self.parse_table_ref()
        while True:
            natural = False
            jt = None
            if self.accept_op(','):
                jt = 'CROSS'
            else:
                if self.accept_kw('NATURAL'):
                    natural = True
                if self.accept_kw('LEFT'):
                    self.accept_kw('OUTER')
                    jt = 'LEFT'
                elif self.accept_kw('RIGHT'):
                    self.accept_kw('OUTER')
                    jt = 'RIGHT'
                elif self.accept_kw('FULL'):
                    self.accept_kw('OUTER')
                    jt = 'FULL'
                elif self.accept_kw('INNER'):
                    jt = 'INNER'
                elif self.accept_kw('CROSS'):
                    jt = 'CROSS'
                if self.is_kw('JOIN'):
                    self.next()
                    if jt is None:
                        jt = 'INNER'
                elif jt is not None or natural:
                    raise self.error()
                else:
                    break
            right = self.parse_table_ref()
            on = None
            using = None
            if self.accept_kw('ON'):
                on = self.parse_expr()
            elif self.accept_kw('USING'):
                self.expect_op('(')
                using = [self.ident()]
                while self.accept_op(','):
                    using.append(self.ident())
                self.expect_op(')')
            left = ('join', left, right, jt, on, using, natural)
        return left

    def parse_table_ref(self):
        if self.accept_op('('):
            if self.is_kw('SELECT', 'VALUES', 'WITH'):
                sel = self.parse_select()
                self.expect_op(')')
                alias = self.parse_alias()
                return ('subq', sel, alias)
            # parenthesised join
            f = self.parse_from()
            self.expect_op(')')
            return f
        name = self.ident()
        if self.accept_op('.'):
            name = self.ident()
        alias = self.parse_alias()
        if self.accept_kw('INDEXED'):
            self.expect_kw('BY')
            self.ident()
        elif self.is_kw('NOT') and self.peek().kind == 'id' and self.peek().up == 'INDEXED':
            self.next()
            self.next()
        return ('table', name, alias)

    def parse_alias(self):
        if self.accept_kw('AS'):
            return self.ident()
        return self.accept_ident()

    # ------------------------------------------------------------ expressions
    def parse_expr_list(self):
        es = [self.parse_expr()]
        while self.accept_op(','):
            es.append(self.parse_expr())
        return es

    def parse_expr(self, minprec=0):
        left = self.parse_prefix()
        while True:
            t = self.tok
            if t.kind == 'op':
                op = t.val
                if op in ('=', '==', '!=', '<>'):
                    prec = 4
                elif op in ('<', '<=', '>', '>='):
                    prec = 5
                elif op in ('&', '|', '<<', '>>'):
                    prec = 6
                elif op in ('+', '-'):
                    prec = 7
                elif op in ('*', '/', '%'):
                    prec = 8
                elif op in ('||', '->', '->>'):
                    prec = 9
                else:
                    break
                if prec < minprec:
                    break
                self.next()
                right = self.parse_expr(prec + 1)
                if op == '==':
                    op = '='
                elif op == '<>':
                    op = '!='
                left = ('bin', op, left, right)
                continue
            if t.kind != 'id':
                break
            kw = t.up
            if kw == 'OR':
                if 1 < minprec:
                    break
                self.next()
                left = ('bin', 'OR', left, self.parse_expr(2))
            elif kw == 'AND':
                if 2 < minprec:
                    break
                self.next()
                left = ('bin', 'AND', left, self.parse_expr(3))
            elif kw == 'COLLATE':
                self.next()
                left = ('collate', left, self.ident())
            elif kw in ('IS', 'ISNULL', 'NOTNULL', 'NOT', 'IN', 'LIKE', 'GLOB', 'MATCH', 'REGEXP', 'BETWEEN'):
                if 4 < minprec:
                    break
                neg = False
                if kw == 'NOT':
                    nk = self.peek()
                    if nk.kind != 'id' or nk.up not in ('IN', 'LIKE', 'GLOB', 'MATCH', 'REGEXP', 'BETWEEN', 'NULL'):
                        break
                    self.next()
                    neg = True
                    kw = self.tok.up
                if kw == 'ISNULL':
                    self.next()
                    left = ('isnull', left, False)
                elif kw == 'NOTNULL':
                    self.next()
                    left = ('isnull', left, True)
                elif kw == 'NULL':
                    self.next()
                    left = ('isnull', left, True)
                elif kw == 'IS':
                    self.next()
                    neg = bool(self.accept_kw('NOT'))
                    if self.accept_kw('DISTINCT'):
                        self.expect_kw('FROM')
                        neg = not neg
                    right = self.parse_expr(5)
                    left = ('bin', 'ISNOT' if neg else 'IS', left, right)
                elif kw == 'IN':
                    self.next()
                    left = self.parse_in(left, neg)
                elif kw == 'BETWEEN':
                    self.next()
                    lo = self.parse_expr(5)
                    self.expect_kw('AND')
                    hi = self.parse_expr(5)
                    left = ('between', left, lo, hi, neg)
                else:
                    self.next()
                    pat = self.parse_expr(5)
                    esc = None
                    if self.accept_kw('ESCAPE'):
                        esc = self.parse_expr(5)
                    left = ('like', kw, left, pat, esc, neg)
            else:
                break
        return left

    def parse_in(self, left, neg):
        if self.accept_op('('):
            if self.is_kw('SELECT', 'VALUES', 'WITH'):
                sel = self.parse_select()
                self.expect_op(')')
                return ('insub', left, sel, neg)
            if self.accept_op(')'):
                return ('inlist', left, [], neg)
            items = self.parse_expr_list()
            self.expect_op(')')
            return ('inlist', left, items, neg)
        name = self.qualified_name()
        sel = {'type': 'select', 'with': None, 'order': None, 'limit': None, 'offset': None,
               'body': {'kind': 'core', 'distinct': False, 'cols': [('star', None)],
                        'from': ('table', name, None), 'where': None, 'group': None,
                        'having': None, 'windows': None}}
        return ('insub', left, sel, neg)

    def parse_prefix(self):
        t = self.tok
        if t.kind == 'op':
            if t.val in ('-', '+'):
                self.next()
                nt = self.tok
                if t.val == '-' and nt.kind == 'float' and nt.up == 'BIG' and nt.val == 9.2233720368547758e18 \
                        and self.src[nt.start:nt.end] == '9223372036854775808':
                    self.next()
                    return ('lit', INT_MIN)
                e = self.parse_expr(10)
                if t.val == '-' and e[0] == 'lit' and e[1] is not None and type(e[1]) in (int, float):
                    return ('lit', -e[1]) if not (type(e[1]) is int and e[1] == INT_MIN) else ('un', '-', e)
                return ('un', t.val, e)
            if t.val == '~':
                self.next()
                return ('un', '~', self.parse_expr(10))
        elif t.kind == 'id' and t.up == 'NOT':
            self.next()
            return ('un', 'NOT', self.parse_expr(4))
        return self.parse_primary()

    def parse_primary(self):
        t = self.next()
        k = t.kind
        if k == 'int' or k == 'float':
            return ('lit', t.val)
        if k == 'str':
            return ('lit', t.val)
        if k == 'blob':
            return ('lit', t.val)
        if k == 'var':
            raise parse_error('parameters are not supported')
        if k == 'op':
            if t.val == '(':
                if self.is_kw('SELECT', 'VALUES', 'WITH'):
                    sel = self.parse_select()
                    self.expect_op(')')
                    return ('subq', sel)
                es = self.parse_expr_list()
                self.expect_op(')')
                if len(es) == 1:
                    return ('paren', es[0])
                return ('row', es)
            raise self.error(t)
        if k == 'qid':
            return self.parse_column_or_call(t, True)
        if k == 'id':
            up = t.up
            if up == 'NULL':
                return ('lit', None)
            if up == 'TRUE':
                return ('lit', 1)
            if up == 'FALSE':
                return ('lit', 0)
            if up in ('CURRENT_TIME', 'CURRENT_DATE', 'CURRENT_TIMESTAMP'):
                return ('func', up.lower(), [], False, False, None, None)
            if up == 'CASE':
                return self.parse_case()
            if up == 'CAST':
                self.expect_op('(')
                e = self.parse_expr()
                self.expect_kw('AS')
                ty = self.parse_typename()
                self.expect_op(')')
                return ('cast', e, ty)
            if up == 'EXISTS':
                self.expect_op('(')
                sel = self.parse_select()
                self.expect_op(')')
                return ('exists', sel, False)
            if up == 'RAISE':
                return self.parse_raise()
            if up in ('LIKE', 'GLOB') and self.is_op('('):
                return self.parse_call(t.val)
            if up in RESERVED:
                raise self.error(t)
            return self.parse_column_or_call(t, False)
        raise self.error(t)

    def parse_raise(self):
        self.expect_op('(')
        kind = self.accept_kw('IGNORE', 'ROLLBACK', 'ABORT', 'FAIL')
        if not kind:
            raise self.error()
        msg = None
        if kind != 'IGNORE':
            self.expect_op(',')
            t = self.next()
            if t.kind != 'str':
                raise self.error(t)
            msg = t.val
        self.expect_op(')')
        return ('raise', kind, msg)

    def parse_column_or_call(self, t, quoted):
        if not quoted and self.is_op('('):
            return self.parse_call(t.val)
        if self.accept_op('.'):
            t2 = self.next()
            if t2.kind not in ('id', 'qid', 'str'):
                raise self.error(t2)
            if self.accept_op('.'):
                t3 = self.next()
                if t3.kind not in ('id', 'qid', 'str'):
                    raise self.error(t3)
                return ('col', t2.val, t3.val)
            return ('col', t.val, t2.val)
        return ('col', None, t.val)

    def parse_call(self, name):
        self.expect_op('(')
        distinct = False
        star = False
        args = []
        if self.accept_op('*'):
            star = True
        elif not self.is_op(')'):
            if self.accept_kw('DISTINCT'):
                distinct = True
            args = self.parse_expr_list()
        self.expect_op(')')
        flt = None
        over = None
        if self.is_kw('FILTER') and self.peek().kind == 'op' and self.peek().val == '(':
            self.next()
            self.next()
            self.expect_kw('WHERE')
            flt = self.parse_expr()
            self.expect_op(')')
        if self.accept_kw('OVER'):
            if self.is_op('('):
                over = self.parse_window_spec()
            else:
                over = ('window', self.ident().lower(), None, None, None)
        return ('func', name.lower(), args, distinct, star, flt, over)

    def parse_window_spec(self):
        self.expect_op('(')
        base = None
        t = self.tok
        if t.kind in ('id', 'qid') and not (t.kind == 'id' and t.up in ('PARTITION', 'ORDER', 'ROWS', 'RANGE', 'GROUPS')):
            base = self.ident().lower()
        part = None
        order = None
        frame = None
        if self.accept_kw('PARTITION'):
            self.expect_kw('BY')
            part = self.parse_expr_list()
        if self.accept_kw('ORDER'):
            self.expect_kw('BY')
            order = self.parse_order_terms()
        unit = self.accept_kw('ROWS', 'RANGE', 'GROUPS')
        if unit:
            if self.accept_kw('BETWEEN'):
                start = self.parse_frame_bound()
                self.expect_kw('AND')
                end = self.parse_frame_bound()
            else:
                start = self.parse_frame_bound()
                end = ('current',)
            excl = None
            if self.accept_kw('EXCLUDE'):
                if self.accept_kw('NO'):
                    self.expect_kw('OTHERS')
                    excl = 'NO OTHERS'
                elif self.accept_kw('CURRENT'):
                    self.expect_kw('ROW')
                    excl = 'CURRENT ROW'
                elif self.accept_kw('GROUP'):
                    excl = 'GROUP'
                elif self.accept_kw('TIES'):
                    excl = 'TIES'
                else:
                    raise self.error()
            frame = (unit, start, end, excl)
        self.expect_op(')')
        return ('window', base, part, order, frame)

    def parse_frame_bound(self):
        if self.accept_kw('UNBOUNDED'):
            k = self.accept_kw('PRECEDING', 'FOLLOWING')
            if not k:
                raise self.error()
            return ('unbounded', k)
        if self.accept_kw('CURRENT'):
            self.expect_kw('ROW')
            return ('current',)
        e = self.parse_expr()
        k = self.accept_kw('PRECEDING', 'FOLLOWING')
        if not k:
            raise self.error()
        return ('offset', e, k)

    def parse_case(self):
        base = None
        if not self.is_kw('WHEN'):
            base = self.parse_expr()
        whens = []
        while self.accept_kw('WHEN'):
            w = self.parse_expr()
            self.expect_kw('THEN')
            whens.append((w, self.parse_expr()))
        if not whens:
            raise self.error()
        els = None
        if self.accept_kw('ELSE'):
            els = self.parse_expr()
        self.expect_kw('END')
        return ('case', base, whens, els)

    def parse_typename(self):
        words = []
        while self.tok.kind in ('id', 'qid') and not (self.tok.kind == 'id' and self.tok.up in COLUMN_CONSTRAINT_WORDS):
            words.append(self.next().val)
        name = ' '.join(words)
        if self.accept_op('('):
            nums = []
            while not self.is_op(')'):
                t = self.next()
                if t.kind == 'eof':
                    raise self.error(t)
                nums.append(self.src[t.start:t.end])
            self.next()
            name += '(' + ''.join(nums) + ')'
        return name

    # ------------------------------------------------------------ INSERT / UPDATE / DELETE
    def parse_conflict_clause(self):
        if self.accept_kw('ON'):
            self.expect_kw('CONFLICT')
            k = self.accept_kw('ROLLBACK', 'ABORT', 'FAIL', 'IGNORE', 'REPLACE')
            if not k:
                raise self.error()
            return k
        return None

    def parse_insert(self, with_clause):
        verb = self.next().up
        action = 'ABORT'
        if verb == 'REPLACE':
            action = 'REPLACE'
        elif self.accept_kw('OR'):
            action = self.accept_kw('ABORT', 'FAIL', 'IGNORE', 'REPLACE', 'ROLLBACK')
            if not action:
                raise self.error()
        self.expect_kw('INTO')
        table = self.qualified_name()
        alias = None
        if self.accept_kw('AS'):
            alias = self.ident()
        cols = None
        if self.accept_op('('):
            cols = [self.ident()]
            while self.accept_op(','):
                cols.append(self.ident())
            self.expect_op(')')
        source = None
        default_values = False
        if self.accept_kw('DEFAULT'):
            self.expect_kw('VALUES')
            default_values = True
        else:
            source = self.parse_select()
        upserts = []
        while self.is_kw('ON') and self.peek().kind == 'id' and self.peek().up == 'CONFLICT':
            self.next()
            self.next()
            target = None
            twhere = None
            if self.accept_op('('):
                target = [self.parse_expr()]
                while self.accept_op(','):
                    target.append(self.parse_expr())
                self.expect_op(')')
                if self.accept_kw('WHERE'):
                    twhere = self.parse_expr()
            self.expect_kw('DO')
            if self.accept_kw('NOTHING'):
                upserts.append({'target': target, 'twhere': twhere, 'do': 'NOTHING'})
            else:
                self.expect_kw('UPDATE')
                self.expect_kw('SET')
                sets = self.parse_assignments()
                uw = None
                if self.accept_kw('WHERE'):
                    uw = self.parse_expr()
                upserts.append({'target': target, 'twhere': twhere, 'do': 'UPDATE', 'sets': sets, 'where': uw})
        returning = self.parse_returning()
        return {'type': 'insert', 'with': with_clause, 'action': action, 'table': table, 'alias': alias,
                'cols': cols, 'source': source, 'default_values': default_values, 'upserts': upserts,
                'returning': returning}

    def parse_returning(self):
        if not self.accept_kw('RETURNING'):
            return None
        cols = []
        while True:
            cols.append(self.parse_result_col())
            if not self.accept_op(','):
                break
        return cols

    def parse_assignments(self):
        sets = []
        while True:
            if self.accept_op('('):
                names = [self.ident()]
                while self.accept_op(','):
                    names.append(self.ident())
                self.expect_op(')')
            else:
                names = [self.ident()]
            self.expect_op('=')
            e = self.parse_expr()
            sets.append((names, e))
            if not self.accept_op(','):
                break
        return sets

    def parse_update(self, with_clause):
        self.next()
        action = 'ABORT'
        if self.accept_kw('OR'):
            action = self.accept_kw('ABORT', 'FAIL', 'IGNORE', 'REPLACE', 'ROLLBACK')
            if not action:
                raise self.error()
        table = self.qualified_name()
        alias = None
        if self.accept_kw('AS'):
            alias = self.ident()
        else:
            alias = self.accept_ident()
        self.expect_kw('SET')
        sets = self.parse_assignments()
        frm = None
        if self.accept_kw('FROM'):
            frm = self.parse_from()
        where = None
        if self.accept_kw('WHERE'):
            where = self.parse_expr()
        returning = self.parse_returning()
        order = limit = offset = None
        if self.accept_kw('ORDER'):
            self.expect_kw('BY')
            order = self.parse_order_terms()
        if self.accept_kw('LIMIT'):
            limit = self.parse_expr()
            if self.accept_kw('OFFSET'):
                offset = self.parse_expr()
        return {'type': 'update', 'with': with_clause, 'action': action, 'table': table, 'alias': alias,
                'sets': sets, 'from': frm, 'where': where, 'returning': returning,
                'order': order, 'limit': limit, 'offset': offset}

    def parse_delete(self, with_clause):
        self.next()
        self.expect_kw('FROM')
        table = self.qualified_name()
        alias = None
        if self.accept_kw('AS'):
            alias = self.ident()
        else:
            alias = self.accept_ident()
        where = None
        if self.accept_kw('WHERE'):
            where = self.parse_expr()
        returning = self.parse_returning()
        order = limit = offset = None
        if self.accept_kw('ORDER'):
            self.expect_kw('BY')
            order = self.parse_order_terms()
        if self.accept_kw('LIMIT'):
            limit = self.parse_expr()
            if self.accept_kw('OFFSET'):
                offset = self.parse_expr()
        return {'type': 'delete', 'with': with_clause, 'table': table, 'alias': alias, 'where': where,
                'returning': returning, 'order': order, 'limit': limit, 'offset': offset}

    # ------------------------------------------------------------ DDL
    def parse_if_not_exists(self):
        if self.is_kw('IF'):
            self.next()
            self.expect_kw('NOT')
            self.expect_kw('EXISTS')
            return True
        return False

    def parse_if_exists(self):
        if self.is_kw('IF'):
            self.next()
            self.expect_kw('EXISTS')
            return True
        return False

    def parse_create(self):
        self.next()
        temp = bool(self.accept_kw('TEMP', 'TEMPORARY'))
        unique = False
        if self.accept_kw('UNIQUE'):
            unique = True
            if not self.is_kw('INDEX'):
                raise self.error()
        kw = self.tok.up if self.tok.kind == 'id' else None
        if kw == 'TABLE':
            self.next()
            return self.parse_create_table(temp)
        if kw == 'INDEX':
            self.next()
            return self.parse_create_index(unique)
        if kw == 'VIEW':
            self.next()
            ine = self.parse_if_not_exists()
            name_start = self.tok.start
            name = self.qualified_name()
            cols = None
            if self.accept_op('('):
                cols = [self.ident()]
                while self.accept_op(','):
                    cols.append(self.ident())
                self.expect_op(')')
            self.expect_kw('AS')
            sel = self.parse_select()
            sql = 'CREATE VIEW ' + self.src[name_start:self.prev_end]
            return {'type': 'create_view', 'name': name, 'cols': cols, 'select': sel,
                    'if_not_exists': ine, 'schema_sql': sql}
        if kw == 'TRIGGER':
            self.next()
            return self.parse_create_trigger()
        raise self.error()

    def parse_create_table(self, temp):
        ine = self.parse_if_not_exists()
        name_start = self.tok.start
        name = self.qualified_name()
        if self.accept_kw('AS'):
            sel = self.parse_select()
            sql = 'CREATE TABLE ' + self.src[name_start:self.prev_end]
            return {'type': 'create_table', 'name': name, 'if_not_exists': ine, 'select': sel,
                    'columns': None, 'constraints': [], 'schema_sql': sql, 'temp': temp}
        self.expect_op('(')
        columns = []
        constraints = []
        while True:
            t = self.tok
            if t.kind == 'id' and t.up in ('CONSTRAINT', 'PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN'):
                constraints.append(self.parse_table_constraint())
            else:
                columns.append(self.parse_column_def())
            if not self.accept_op(','):
                break
        self.expect_op(')')
        without_rowid = False
        strict = False
        while True:
            if self.accept_kw('WITHOUT'):
                self.expect_kw('ROWID')
                without_rowid = True
            elif self.is_kw('STRICT'):
                self.next()
                strict = True
            else:
                break
            self.accept_op(',')
        sql = 'CREATE TABLE ' + self.src[name_start:self.prev_end]
        return {'type': 'create_table', 'name': name, 'if_not_exists': ine, 'select': None,
                'columns': columns, 'constraints': constraints, 'schema_sql': sql,
                'without_rowid': without_rowid, 'strict': strict, 'temp': temp}

    def parse_column_def(self):
        name = self.ident()
        col = {'name': name, 'type': self.parse_typename(), 'pk': False, 'autoinc': False, 'notnull': False,
               'unique': False, 'checks': [], 'default': None, 'collate': None, 'generated': None,
               'pk_desc': False}
        while True:
            cname = None
            if self.accept_kw('CONSTRAINT'):
                cname = self.ident()
            if self.accept_kw('PRIMARY'):
                self.expect_kw('KEY')
                col['pk'] = True
                if self.accept_kw('DESC'):
                    col['pk_desc'] = True
                else:
                    self.accept_kw('ASC')
                self.parse_conflict_clause()
                if self.accept_kw('AUTOINCREMENT'):
                    col['autoinc'] = True
            elif self.accept_kw('NOT'):
                self.expect_kw('NULL')
                col['notnull'] = True
                self.parse_conflict_clause()
            elif self.accept_kw('NULL'):
                self.parse_conflict_clause()
            elif self.accept_kw('UNIQUE'):
                col['unique'] = True
                self.parse_conflict_clause()
            elif self.accept_kw('CHECK'):
                self.expect_op('(')
                s = self.tok.start
                e = self.parse_expr()
                text = self.src[s:self.prev_end]
                self.expect_op(')')
                col['checks'].append((e, text, cname))
            elif self.accept_kw('DEFAULT'):
                if self.accept_op('('):
                    col['default'] = self.parse_expr()
                    self.expect_op(')')
                else:
                    t = self.tok
                    if t.kind == 'op' and t.val in ('+', '-'):
                        self.next()
                        nt = self.next()
                        if nt.kind not in ('int', 'float'):
                            raise self.error(nt)
                        col['default'] = ('lit', -nt.val if t.val == '-' else nt.val)
                    elif t.kind in ('int', 'float', 'str', 'blob'):
                        self.next()
                        col['default'] = ('lit', t.val)
                    elif t.kind == 'id' and t.up in ('NULL', 'TRUE', 'FALSE', 'CURRENT_TIME', 'CURRENT_DATE',
                                                     'CURRENT_TIMESTAMP'):
                        col['default'] = self.parse_primary()
                    elif t.kind in ('id', 'qid'):
                        self.next()
                        col['default'] = ('lit', t.val)
                    else:
                        raise self.error()
            elif self.accept_kw('COLLATE'):
                col['collate'] = self.ident()
            elif self.is_kw('REFERENCES'):
                self.parse_references()
            elif self.is_kw('GENERATED', 'AS'):
                if self.accept_kw('GENERATED'):
                    self.expect_kw('ALWAYS')
                self.expect_kw('AS')
                self.expect_op('(')
                col['generated'] = self.parse_expr()
                self.expect_op(')')
                stored = bool(self.accept_kw('STORED'))
                if not stored:
                    self.accept_kw('VIRTUAL')
                col['gen_stored'] = stored
            else:
                if cname is not None:
                    raise self.error()
                break
        return col

    def parse_references(self):
        self.expect_kw('REFERENCES')
        ft = self.qualified_name()
        fcols = None
        if self.accept_op('('):
            fcols = [self.ident()]
            while self.accept_op(','):
                fcols.append(self.ident())
            self.expect_op(')')
        while True:
            if self.accept_kw('ON'):
                if not self.accept_kw('DELETE', 'UPDATE'):
                    raise self.error()
                if self.accept_kw('SET'):
                    if not self.accept_kw('NULL', 'DEFAULT'):
                        raise self.error()
                elif self.accept_kw('NO'):
                    self.expect_kw('ACTION')
                elif not self.accept_kw('CASCADE', 'RESTRICT'):
                    raise self.error()
            elif self.accept_kw('MATCH'):
                self.ident()
            elif self.is_kw('NOT') and self.peek().kind == 'id' and self.peek().up == 'DEFERRABLE':
                self.next()
                self.next()
                if self.accept_kw('INITIALLY'):
                    self.accept_kw('DEFERRED', 'IMMEDIATE')
            elif self.accept_kw('DEFERRABLE'):
                if self.accept_kw('INITIALLY'):
                    self.accept_kw('DEFERRED', 'IMMEDIATE')
            else:
                break
        return (ft, fcols)

    def parse_indexed_columns(self):
        self.expect_op('(')
        cols = []
        while True:
            s = self.tok.start
            e = self.parse_expr()
            text = self.src[s:self.prev_end]
            coll = None
            if e[0] == 'collate':
                coll = e[2]
                e = e[1]
            if self.accept_kw('COLLATE'):
                coll = self.ident()
            desc = False
            if self.accept_kw('DESC'):
                desc = True
            else:
                self.accept_kw('ASC')
            cols.append((e, coll, desc, text))
            if not self.accept_op(','):
                break
        self.expect_op(')')
        return cols

    def parse_table_constraint(self):
        cname = None
        if self.accept_kw('CONSTRAINT'):
            cname = self.ident()
        if self.accept_kw('PRIMARY'):
            self.expect_kw('KEY')
            cols = self.parse_indexed_columns()
            self.parse_conflict_clause()
            return {'kind': 'pk', 'cols': cols, 'name': cname}
        if self.accept_kw('UNIQUE'):
            cols = self.parse_indexed_columns()
            self.parse_conflict_clause()
            return {'kind': 'unique', 'cols': cols, 'name': cname}
        if self.accept_kw('CHECK'):
            self.expect_op('(')
            s = self.tok.start
            e = self.parse_expr()
            text = self.src[s:self.prev_end]
            self.expect_op(')')
            return {'kind': 'check', 'expr': e, 'text': text, 'name': cname}
        if self.accept_kw('FOREIGN'):
            self.expect_kw('KEY')
            self.expect_op('(')
            self.ident()
            while self.accept_op(','):
                self.ident()
            self.expect_op(')')
            self.parse_references()
            return {'kind': 'fk', 'name': cname}
        raise self.error()

    def parse_create_index(self, unique):
        ine = self.parse_if_not_exists()
        name = self.qualified_name()
        self.expect_kw('ON')
        table = self.qualified_name()
        cols = self.parse_indexed_columns()
        where = None
        if self.accept_kw('WHERE'):
            where = self.parse_expr()
        return {'type': 'create_index', 'name': name, 'table': table, 'cols': cols, 'unique': unique,
                'where': where, 'if_not_exists': ine}

    def parse_create_trigger(self):
        ine = self.parse_if_not_exists()
        name_start = self.tok.start
        name = self.qualified_name()
        timing = 'BEFORE'
        if self.accept_kw('BEFORE'):
            timing = 'BEFORE'
        elif self.accept_kw('AFTER'):
            timing = 'AFTER'
        elif self.accept_kw('INSTEAD'):
            self.expect_kw('OF')
            timing = 'INSTEAD'
        ev = self.accept_kw('DELETE', 'INSERT', 'UPDATE')
        if not ev:
            raise self.error()
        cols = None
        if ev == 'UPDATE' and self.accept_kw('OF'):
            cols = [self.ident()]
            while self.accept_op(','):
                cols.append(self.ident())
        self.expect_kw('ON')
        table = self.qualified_name()
        if self.accept_kw('FOR'):
            self.expect_kw('EACH')
            self.expect_kw('ROW')
        when = None
        if self.accept_kw('WHEN'):
            when = self.parse_expr()
        self.expect_kw('BEGIN')
        body = []
        while True:
            while self.accept_op(';'):
                pass
            if self.accept_kw('END'):
                break
            t = self.tok
            if t.kind != 'id':
                raise self.error()
            if t.up in ('SELECT', 'VALUES', 'WITH'):
                st = self.parse_with_stmt()
            elif t.up in ('INSERT', 'REPLACE'):
                st = self.parse_insert(None)
            elif t.up == 'UPDATE':
                st = self.parse_update(None)
            elif t.up == 'DELETE':
                st = self.parse_delete(None)
            else:
                raise self.error()
            body.append(st)
            if not self.is_op(';'):
                raise self.error()
        sql = 'CREATE TRIGGER ' + self.src[name_start:self.prev_end]
        return {'type': 'create_trigger', 'name': name, 'timing': timing, 'event': ev, 'cols': cols,
                'table': table, 'when': when, 'body': body, 'if_not_exists': ine, 'schema_sql': sql}

    def parse_drop(self):
        self.next()
        kw = self.accept_kw('TABLE', 'INDEX', 'VIEW', 'TRIGGER')
        if not kw:
            raise self.error()
        ie = self.parse_if_exists()
        name = self.qualified_name()
        return {'type': 'drop', 'what': kw.lower(), 'name': name, 'if_exists': ie}

    def parse_alter(self):
        self.next()
        self.expect_kw('TABLE')
        table = self.qualified_name()
        if self.accept_kw('RENAME'):
            if self.accept_kw('TO'):
                return {'type': 'alter', 'op': 'rename', 'table': table, 'new': self.ident()}
            self.accept_kw('COLUMN')
            old = self.ident()
            self.expect_kw('TO')
            return {'type': 'alter', 'op': 'rename_column', 'table': table, 'old': old, 'new': self.ident()}
        if self.accept_kw('ADD'):
            self.accept_kw('COLUMN')
            s = self.tok.start
            col = self.parse_column_def()
            col['text'] = self.src[s:self.prev_end]
            return {'type': 'alter', 'op': 'add', 'table': table, 'column': col}
        if self.accept_kw('DROP'):
            self.accept_kw('COLUMN')
            return {'type': 'alter', 'op': 'drop', 'table': table, 'name': self.ident()}
        raise self.error()
